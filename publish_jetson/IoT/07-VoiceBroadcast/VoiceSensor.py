import time
import socket
import os
import json
import math
from UdpPackage import *
from RS232Module import *







class VoiceSensor(object):
    def __init__(self, modIndex,comIndex,txpin,rxpin):
        self.existing_data = []
        self.modIndex = modIndex
        self.comIndex = comIndex
        self.txpin = txpin
        self.rxpin = rxpin
    def init(self):
        ret = smartSensorlib.RS232Init(self.modIndex, self.comIndex, self.txpin, self.rxpin, 9600, 0, 8,1)
        if ret <0 :
            raise ValueError("mod disconnect")
    def SendAscIIData(self, data, size):
        ret = smartSensorlib.RS232ModSendAscIIData(self.modIndex, self.comIndex, size,data)
        return ret
    def SendHexData(self, data, size):
        ret = smartSensorlib.RS232ModSendHexData(self.modIndex, self.comIndex,size, data)
        if ret <0 :
            raise ValueError("mod disconnect")
    def uninit(self):
        ret = smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)
        if ret <0 :
            raise ValueError("mod disconnect")
    
