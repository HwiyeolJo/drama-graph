from knowledge_extraction.oie import *
from knowledge_extraction.frame import *
from preprocessing.sentence_divider import *
from utils.macro import *

class extractor:
    def __init__(self, config, input):
        self.input = input
        self.config = config

        if config['extraction']['load']:
            self.output = jsonload(self.config['extraction']['output_path'])
            return
        self.frame = frame(config, self.input)
        self.oie = oie(config, self.frame.output)
        self.output = self.oie.output


    def save_output(self):
        if self.config['extraction']['load']:
            return
        jsondump(self.output, self.config['extraction']['output_path'])
        return
