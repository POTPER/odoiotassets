import time
import socket
import os
import json
import math
from UdpPackage import *
from RS232Module import *
import time
from GpioController import *





class ZigbeeSensor(object):
    def __init__(self, modIndex,comIndex,txpin,rxpin,rstpin):
        self.existing_data = []
        self.modIndex = modIndex
        self.comIndex = comIndex
        self.txpin = txpin
        self.rxpin = rxpin
        self.rstpin = rstpin
    def init(self):
        smartSensorlib.GpioOutInit(self.modIndex,self.rstpin)
        smartSensorlib.GpioSetLevel(self.modIndex,self.rstpin,1)
        smartSensorlib.RS232Init(self.modIndex, self.comIndex, self.txpin, self.rxpin, 115200, 0, 8,1)
    def readAsciiData(self,readsize,buffer,timeout):
        return smartSensorlib.RS232ModReadAscIIData(self.modIndex,self.comIndex,readsize,buffer,timeout)
    def resetmod(self):
        smartSensorlib.GpioSetLevel(self.modIndex,self.rstpin,0)
        time.sleep(0.1)
        smartSensorlib.GpioSetLevel(self.modIndex,self.rstpin,1)
    def SendAscIIData(self, data, size):
        ret = smartSensorlib.RS232ModSendAscIIData(self.modIndex, self.comIndex, size,data)
        return ret
    def SendHexData(self, data, size):
        smartSensorlib.RS232ModSendHexData(self.modIndex, self.comIndex,size, data)
    
    def uninit(self):
        smartSensorlib.RS232Uninit(self.modIndex, self.comIndex)
    
