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
        smartSensorlib.RS232Init(self.modIndex, self.comIndex, self.txpin, self.rxpin, 9600, 0, 8,1)

    def SendAscIIData(self, data, size):
        ret = smartSensorlib.RS232ModSendAscIIData(self.modIndex, self.comIndex, size,data)
        return ret
    def SendHexData(self, data, size):
        smartSensorlib.RS232ModSendHexData(self.modIndex, self.comIndex,size, data)
    
    def uninit(self):
        smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)
    
