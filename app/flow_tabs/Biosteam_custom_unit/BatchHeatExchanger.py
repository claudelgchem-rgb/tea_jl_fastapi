import biosteam as bst
from biosteam import Unit, Stream, settings, main_flowsheet
import numpy as np, pandas as pd, copy, json, os, sys, pickle, math
import streamlit as st

class BatchHeatExchanger(bst.units.heat_exchange.HXutility):
    """
    A custom heat exchanger for batch process. Heat transfer area is enlarged to hold batch volume
    Input:
    scale factor: Scale up factor. Same as batch time
    """
    def _init(self, T=403.15, scale_factor=1.0, hxn_ok=True, heat_transfer_efficiency=0.7, **kwargs):
        super()._init(**kwargs)
        self.scale_factor = scale_factor
        self.T = T if T>200 else T+273
        self.hxn_ok = hxn_ok
        self.heat_transfer_efficiency = heat_transfer_efficiency
        self.isfurnace=False

    def _design(self):
        super()._design()
        Design = self.design_results
        if self.outs[0].F_mass==0:
            return
        else:
            Design['Area'] = Design['Area'] * self.scale_factor
