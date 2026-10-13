import time
import socket
import os
import json
import math
from UdpPackage import *
from RS232Module import *







class AirQualitySensor(object):
    def __init__(self, modIndex,comIndex,txpin,rxpin):
        self.existing_data = []
        self.modIndex = modIndex
        self.comIndex = comIndex
        self.txpin = txpin
        self.rxpin = rxpin
    def init(self):
        ret = smartSensorlib.RS232Init(self.modIndex, self.comIndex, self.txpin, self.rxpin, 9600, 0, 8,1)
        if ret<0:
            raise ValueError("mod disconnect")
    def SendHexDataAndReadData(self, senddata, size,readdata,readdatasize,timeout):
        ret = smartSensorlib.RS232ModWriteReadHexData(self.modIndex, self.comIndex, readdatasize,readdata,size,senddata,timeout)
        return ret
    def uninit(self):
        ret = smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)
        if ret<0:
            raise ValueError("mod disconnect")
    
