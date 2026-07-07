import biosteam as bst, thermosteam as tmo
from biosteam import Unit, Stream, settings, main_flowsheet
import numpy as np, pandas as pd, copy, json, os, sys, pickle, math
import streamlit as st

class CustomSplitter(bst.Unit):
    _N_ins = 1
    _N_outs = 0
    _outs_size_is_fixed = False
    _graphics = tmo._graphics.splitter_graphics
    
    def _init(self, split_ratio = []):
        self.split_ratio = split_ratio

    #def _setup(self):
    #    outs = [bst.Stream() for i in range(len(self.split_ratio))]
    #    self._init_outlets(outs)
    #    super()._setup()

    def _run(self):
        
        tmp = sum(self.split_ratio)
        if tmp==0:
            return
        split_ratio = [i/tmp for i in self.split_ratio]
        for j,i in enumerate(self.outs):
            i.copy_like(self.ins[0])
            i.scale(split_ratio[j])

