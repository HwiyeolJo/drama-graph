"""
modified by haeyong.kang
"""
import math
import torch
import torch.nn as nn
from torch.autograd import Variable
import warnings
import pdb
warnings.filterwarnings("ignore", category=UserWarning)

# class_weights = torch.Tensor([10.63357693,10.25937481,9.910614188,9.455261645,8.68100945,8.409727905,8.212316452,7.475313693,
#                 6.576027836,5.919537747,5.821042943,4.519957117,4.490945839,4.30843203,4.276829839,4.135279915,
#                 3.900163666,3.694241614,3.655639298,3.602931832,3.533784655,3.484508773,3.291107064,3.230329463,
#                 2.893669817,2.678749471,2.581879563,2.484692336,2.357443941,2.055491662,1.836455018,1.315700191,
#                 1.175158485,1.125626386,0.9316769131,0.8549479004,0.8487255722,0.6159237339,0.4868420273,0.4741085253,
#                 0.3957966748,0.3292965746,.3051680747,0.2963278679,0.2893669817,0.1824483342,0.1566632398])


class Relation_YoloLoss(nn.modules.loss._Loss):
    # The loss I borrow from LightNet repo.
    def __init__(self, num_classes, num_relations, anchors, reduction=32,
                 coord_scale=1.0, noobject_scale=1.0,
                 object_scale=5.0, class_scale=1.0, thresh=0.6):

        super(Relation_YoloLoss, self).__init__()
        self.num_classes = num_classes
        self.num_relations = num_relations

        self.num_anchors = len(anchors)
        self.anchor_step = len(anchors[0])
        self.anchors = torch.Tensor(anchors)
        self.reduction = reduction

        self.coord_scale = coord_scale
        self.noobject_scale = noobject_scale
        self.object_scale = object_scale

        self.class_scale = class_scale

        self.thresh = thresh

        # define loss functions
        self.mse = nn.MSELoss(size_average=False)
        self.ce = nn.CrossEntropyLoss(size_average=False)

        # display labels
        self.debug = True

    def forward(self, output, target, device):

        # output : [b, 125, 14, 14]
        batch, channel, height, width = output.size()

        # --------- Get x,y,w,h,conf,cls----------------
        # output : [b, 5, 25, 196]
        output = output.view(batch, self.num_anchors, -1, height * width)

        # coord : [b, 5, 4, 196]
        coord = torch.zeros_like(output[:, :, :4, :])
        coord[:, :, :2, :] = output[:, :, :2, :].sigmoid()
        coord[:, :, 2:4, :] = output[:, :, 2:4, :]

        # conf : [b, 5, 196]
        conf = output[:, :, 4, :].sigmoid()

        # cls : [b * 5, 20, 196]
        # cls : [7840, 20] = [batch * num_anchors * height * width, num_cls]
        cls = output[:, :, 5:-13, :].contiguous().view(
            batch * self.num_anchors, self.num_classes,
            height * width).transpose(1, 2).contiguous().view(
                -1,self.num_classes)
        rel_cls = output[:, :, 52:, :].contiguous().view(
            batch * self.num_anchors, self.num_relations,
            height * width).transpose(1, 2).contiguous().view(
                -1,self.num_relations)

        # -------- Create prediction boxes--------------
        # pred_boxes : [7840, 4]
        pred_boxes = torch.FloatTensor(
            batch * self.num_anchors * height * width, 4)

        # lin_x, y : [196]
        lin_x = torch.range(0, width - 1).repeat(
            height, 1).view(height * width)
        lin_y = torch.range(0, height - 1).repeat(
            width, 1).t().contiguous().view(height * width)

        # anchor_w, h : [5, 1]
        anchor_w = self.anchors[:, 0].contiguous().view(self.num_anchors, 1)
        anchor_h = self.anchors[:, 1].contiguous().view(self.num_anchors, 1)

        if torch.cuda.is_available():
            pred_boxes = Variable(pred_boxes.cuda(device),
                                  requires_grad=False).detach()
            lin_x = Variable(lin_x.cuda(device),
                             requires_grad=False).detach()
            lin_y = Variable(lin_y.cuda(device),
                             requires_grad=False).detach()
            anchor_w = Variable(anchor_w.cuda(device),
                                requires_grad=False).detach()
            anchor_h = Variable(anchor_h.cuda(device),
                                requires_grad=False).detach()

        pred_boxes[:, 0] = (coord[:, :, 0].detach() + lin_x).view(-1)
        pred_boxes[:, 1] = (coord[:, :, 1].detach() + lin_y).view(-1)
        pred_boxes[:, 2] = (coord[:, :, 2].detach().exp() * anchor_w).view(-1)
        pred_boxes[:, 3] = (coord[:, :, 3].detach().exp() * anchor_h).view(-1)
        pred_boxes = pred_boxes.cpu()

        # --------- Get target values ------------------
        coord_mask, conf_mask, cls_mask, tcoord, tconf, tcls, rel_cls_mask, rel_tcls = self.build_targets(pred_boxes, target, height, width)

        # coord_mask : [b, 5, 4, 196]
        coord_mask = coord_mask.expand_as(tcoord)

        # tcls : [16], cls_mask : [b, 5, 196]
        tcls_person = tcls[cls_mask].view(-1).long()
        tcls_relation = rel_tcls[rel_cls_mask].view(-1).long()

        # cls_mask : [7840, 20]
        cls_person_mask = cls_mask.view(-1, 1).repeat(1, self.num_classes)
        cls_rel_mask = rel_cls_mask.view(-1, 1).repeat(1, self.num_relations)

        if torch.cuda.is_available():
            tcoord = Variable(tcoord.cuda(device),
                              requires_grad=False).detach()
            tconf = Variable(tconf.cuda(device),
                             requires_grad=False).detach()
            coord_mask = Variable(coord_mask.cuda(device),
                                  requires_grad=False).detach()
            conf_mask = Variable(conf_mask.cuda(device),
                                 requires_grad=False).detach()
            tcls_person = Variable(tcls_person.cuda(device),
                                   requires_grad=False).detach()
            tcls_relation = Variable(tcls_relation.cuda(device),
                                   requires_grad=False).detach()
            cls_person_mask = Variable(cls_person_mask.cuda(device),
                                       requires_grad=False).detach()
            cls_rel_mask = Variable(cls_rel_mask.cuda(device),
                                       requires_grad=False).detach()

        conf_mask = conf_mask.sqrt()
        cls_person = cls[cls_person_mask].view(-1, self.num_classes)
        cls_rel = rel_cls[cls_rel_mask].view(-1, self.num_relations)

        # --------- Compute losses --------------------
        # Losses for person detection coordinates
        self.loss_coord = self.coord_scale * self.mse(
            coord * coord_mask, tcoord * coord_mask) / batch

        # losses for person detection confidence
        self.loss_conf = self.mse(conf * conf_mask, tconf * conf_mask) / batch

        # losses for person detection
        if self.debug:
            print("tcls_person:{}".format(tcls_person))
        self.loss_cls = self.class_scale * 2 * self.ce(
            cls_person, tcls_person) / batch

        self.loss_rel = self.ce(cls_rel, tcls_relation) / batch

        # total losses
        self.loss_tot = self.loss_coord + self.loss_conf + self.loss_cls + self.loss_rel

        return self.loss_tot, self.loss_coord, self.loss_conf, self.loss_cls, self.loss_rel

    def build_targets(self, pred_boxes, ground_truth, height, width):

        # pred_boxes : [7840, 4]
        # ground_truth : [b, 5]
        # height : 14
        # width : 14

        # batch : [8]
        batch = len(ground_truth)

        # conf_mask : [b, 5, 196]
        conf_mask = torch.ones(
            batch, self.num_anchors, height * width,
            requires_grad=False) * self.noobject_scale

        # coord_mask : [b, 5, 1, 196]
        coord_mask = torch.zeros(
            batch, self.num_anchors, 1, height * width,
            requires_grad=False)

        # cls_mask : [b,5,196]
        cls_mask = torch.zeros(
            batch, self.num_anchors, height * width,
            requires_grad=False).byte()

        rel_cls_mask = torch.zeros(
            batch, self.num_anchors, height * width,
            requires_grad=False).byte()

        # tcoord : [b, 5, 4, 196]
        tcoord = torch.zeros(
            batch, self.num_anchors, 4, height * width,
            requires_grad=False)

        # tconf : [b, 5, 196]
        tconf = torch.zeros(
            batch, self.num_anchors, height * width,
            requires_grad=False)

        # tcls : [b, 5, 196]
        tcls = torch.zeros(
            batch, self.num_anchors, height * width,
            requires_grad=False)

        rel_tcls = torch.zeros(
            batch, self.num_anchors, height * width,
            requires_grad=False)

        for b in range(batch):
            if len(ground_truth[b]) == 0:
                continue

            # ------- Build up tensors --------------------------------
            # cur_pred_boxes : [980, 4]
            cur_pred_boxes = pred_boxes[b * (self.num_anchors * height * width):(
                b + 1) * (self.num_anchors * height * width)]

            # anchors : [5, 4]
            if self.anchor_step == 4:
                anchors = self.anchors.clone()
                anchors[:, :2] = 0
            else:
                anchors = torch.cat(
                    [torch.zeros_like(self.anchors), self.anchors], 1)
                # gt : [:, 4]
            gt = torch.zeros(len(ground_truth[b]), 4)
            rel_gt = torch.zeros(len(ground_truth[b]), 5)
            for i, anno in enumerate(ground_truth[b]):
                gt[i, 0] = (anno[0] + anno[2] / 2) / self.reduction
                gt[i, 1] = (anno[1] + anno[3] / 2) / self.reduction
                gt[i, 2] = anno[2] / self.reduction
                gt[i, 3] = anno[3] / self.reduction

            # ------ Set confidence mask of matching detections to 0
            # iou_gt_pred : [:, 980]
            iou_gt_pred = bbox_ious(gt, cur_pred_boxes)
            # mask : [:, 980]
            mask = (iou_gt_pred > self.thresh).sum(0) >= 1
            # conf_mask[b] : [5, 196]
            conf_mask[b][mask.view_as(conf_mask[b])] = 0

            # ------ Find best anchor for each ground truth -------------
            gt_wh = gt.clone()
            gt_wh[:, :2] = 0
            iou_gt_anchors = bbox_ious(gt_wh, anchors)
            _, best_anchors = iou_gt_anchors.max(1)

            # ------ Set masks and target values for each ground truth --
            for i, anno in enumerate(ground_truth[b]):
                gi = min(width - 1, max(0, int(gt[i, 0])))
                gj = min(height - 1, max(0, int(gt[i, 1])))
                best_n = best_anchors[i]
                iou = iou_gt_pred[i][best_n * height * width + gj * width + gi]
                coord_mask[b][best_n][0][gj * width + gi] = 1
                cls_mask[b][best_n][gj * width + gi] = 1
                rel_cls_mask[b][best_n][gj * width + gi] = 1
                conf_mask[b][best_n][gj * width + gi] = self.object_scale
                tcoord[b][best_n][0][gj * width + gi] = gt[i, 0] - gi
                tcoord[b][best_n][1][gj * width + gi] = gt[i, 1] - gj
                tcoord[b][best_n][2][gj * width + gi] = math.log(
                    max(gt[i, 2], 1.0) / self.anchors[best_n, 0])
                tcoord[b][best_n][3][gj * width + gi] = math.log(
                    max(gt[i, 3], 1.0) / self.anchors[best_n, 1])
                tconf[b][best_n][gj * width + gi] = iou
                tcls[b][best_n][gj * width + gi] = int(anno[4])
                rel_tcls[b][best_n][gj * width + gi] = int(anno[5])

        return coord_mask, conf_mask, cls_mask, tcoord, tconf, tcls, rel_cls_mask, rel_tcls


def bbox_ious(boxes1, boxes2):
    b1x1, b1y1 = (boxes1[:, :2] - (boxes1[:, 2:4] / 2)).split(1, 1)
    b1x2, b1y2 = (boxes1[:, :2] + (boxes1[:, 2:4] / 2)).split(1, 1)
    b2x1, b2y1 = (boxes2[:, :2] - (boxes2[:, 2:4] / 2)).split(1, 1)
    b2x2, b2y2 = (boxes2[:, :2] + (boxes2[:, 2:4] / 2)).split(1, 1)

    dx = (b1x2.min(b2x2.t()) - b1x1.max(b2x1.t())).clamp(min=0)
    dy = (b1y2.min(b2y2.t()) - b1y1.max(b2y1.t())).clamp(min=0)
    intersections = dx * dy

    areas1 = (b1x2 - b1x1) * (b1y2 - b1y1)
    areas2 = (b2x2 - b2x1) * (b2y2 - b2y1)
    unions = (areas1 + areas2.t()) - intersections

    return intersections / unions