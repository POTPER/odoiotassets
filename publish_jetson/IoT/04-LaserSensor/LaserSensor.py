import ctypes
import time
import socket
import os
import json
import math
import numpy as np
from UdpPackage import *

dest_addr = ("127.0.0.1", 8088)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

global_id = 0
max_packet_size = 1000


# 传感器模块信息
class tModInf(ctypes.Structure):
    _fields_ = [
        ("nModType", ctypes.c_int),
        ("nModState", ctypes.c_int),
        ("servport", ctypes.c_int),
        ("sModIP", ctypes.c_char * 64),
        ("sModVer", ctypes.c_char * 64),
    ]


# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")
else:
    smartSensorlib = ctypes.CDLL("./libSmartSensorDriver.so")


# I2C初始化
# 参数1：模块地址
# 参数2：SCL pin 序号
# 参数3：SDA PIN 序号
# 参数4：I2C传感器地址长度
# 参数5：通讯速率
# 参数6：传感器I2C地址
smartSensorlib.I2CInit.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
]
smartSensorlib.I2CInit.restype = ctypes.c_int


# I2C读数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum
# 参数4：bytenum字节数
# 参数5：bigendian
# 参数6：data
smartSensorlib.I2CRead.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CRead.restype = ctypes.c_int

# I2C写数据
# 参数1：模块地址
# 参数2：addr
# 参数3：addrbytenum字节数
# 参数4：bytenum字节数
# 参数5：bigendian
# 参数6：data
smartSensorlib.I2CWrite.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.I2CWrite.restype = ctypes.c_int
# I2C写数据
# 参数1：模块地址
smartSensorlib.I2CUninit.argtypes = [ctypes.c_int]
smartSensorlib.I2CUninit.restype = ctypes.c_int



VL53L1_DEVICEERROR_VCSELCONTINUITYTESTFAILURE = ( 1)
VL53L1_DEVICEERROR_VCSELWATCHDOGTESTFAILURE   = ( 2)
VL53L1_DEVICEERROR_NOVHVVALUEFOUND       =      ( 3)
VL53L1_DEVICEERROR_MSRCNOTARGET          =      ( 4)
VL53L1_DEVICEERROR_RANGEPHASECHECK       =      ( 5)
VL53L1_DEVICEERROR_SIGMATHRESHOLDCHECK   =      ( 6)
VL53L1_DEVICEERROR_PHASECONSISTENCY      =      ( 7)
VL53L1_DEVICEERROR_MINCLIP               =      ( 8)
VL53L1_DEVICEERROR_RANGECOMPLETE         =      ( 9)
VL53L1_DEVICEERROR_ALGOUNDERFLOW         =      ( 10)
VL53L1_DEVICEERROR_ALGOOVERFLOW          =      ( 11)
VL53L1_DEVICEERROR_RANGEIGNORETHRESHOLD     =   ( 12)
VL53L1_DEVICEERROR_USERROICLIP              =   ( 13)
VL53L1_DEVICEERROR_REFSPADCHARNOTENOUGHDPADS =  ( 14)
VL53L1_DEVICEERROR_REFSPADCHARMORETHANTARGET  = ( 15)
VL53L1_DEVICEERROR_REFSPADCHARLESSTHANTARGET =  ( 16)
VL53L1_DEVICEERROR_MULTCLIPFAIL              =  ( 17)
VL53L1_DEVICEERROR_GPHSTREAMCOUNT0READY     =   ( 18)
VL53L1_DEVICEERROR_RANGECOMPLETE_NO_WRAP_CHECK= ( 19)
VL53L1_DEVICEERROR_EVENTCONSISTENCY           = ( 20)
VL53L1_DEVICEERROR_MINSIGNALEVENTCHECK        = ( 21)
VL53L1_DEVICEERROR_RANGECOMPLETE_MERGED_PULSE = ( 22)

VL53L1_RANGESTATUS_RANGE_VALID      = 0 #/*!<The Range is valid. */
VL53L1_RANGESTATUS_SIGMA_FAIL       = 1 #/*!<Sigma Fail. */
VL53L1_RANGESTATUS_SIGNAL_FAIL      = 2 #/*!<Signal fail. */
VL53L1_RANGESTATUS_RANGE_VALID_MIN_RANGE_CLIPPED =3 #/*!<Target is below minimum detection threshold. */
VL53L1_RANGESTATUS_OUTOFBOUNDS_FAIL     = 4 #/*!<Phase out of valid limits -  different to a wrap exit. */
VL53L1_RANGESTATUS_HARDWARE_FAIL    = 5 #/*!<Hardware fail. */
VL53L1_RANGESTATUS_RANGE_VALID_NO_WRAP_CHECK_FAIL  =6 #/*!<The Range is valid but the wraparound check has not been done. */
VL53L1_RANGESTATUS_WRAP_TARGET_FAIL     =7 #/*!<Wrapped target - no matching phase in other VCSEL period timing. */
VL53L1_RANGESTATUS_PROCESSING_FAIL    =  8 #/*!<Internal algo underflow or overflow in lite ranging. */
VL53L1_RANGESTATUS_XTALK_SIGNAL_FAIL     = 9 #/*!<Specific to lite ranging. */
VL53L1_RANGESTATUS_SYNCRONISATION_INT    = 10 #/*!<1st interrupt when starting ranging in back to back mode. Ignore data. */
VL53L1_RANGESTATUS_RANGE_VALID_MERGED_PULSE   =11 #/*!<All Range ok but object is result of multiple pulses merging together.*/
VL53L1_RANGESTATUS_TARGET_PRESENT_LACK_OF_SIGNAL  =12 #/*!<Used  by RQL  as different to phase fail. */
VL53L1_RANGESTATUS_MIN_RANGE_FAIL   =  13 #/*!<User ROI input is not valid e.g. beyond SPAD Array.*/
VL53L1_RANGESTATUS_RANGE_INVALID   =   14 #/*!<lld returned valid range but negative value ! */
VL53L1_RANGESTATUS_NONE     =   255 #/*!<No Update. */


VL53L1_RESULT__RANGE_STATUS         =                                             0x0089
VL53L1_RANGE_CONFIG__VCSEL_PERIOD_A  =                                            0x0060
VL53L1_RANGE_CONFIG__VCSEL_PERIOD_B   =                                           0x0063
VL53L1_RANGE_CONFIG__VALID_PHASE_HIGH =                                           0x0069
VL53L1_SD_CONFIG__WOI_SD0             =                                           0x0078
VL53L1_SD_CONFIG__WOI_SD1             =                                           0x0079
VL53L1_SD_CONFIG__INITIAL_PHASE_SD0   =                                           0x007A
VL53L1_SD_CONFIG__INITIAL_PHASE_SD1   =                                           0x007B
VL53L1_RESULT__PEAK_SIGNAL_COUNT_RATE_CROSSTALK_CORRECTED_MCPS_SD0 =              0x0098
VL53L1_RESULT__FINAL_CROSSTALK_CORRECTED_RANGE_MM_SD0   =                         0x0096
VL53L1_SOFT_RESET                      =                                          0x0000
VL53L1_GPIO__TIO_HV_STATUS             =                                          0x0031
VL53L1_IDENTIFICATION__MODEL_ID        =                                          0x010F
VL53L1_FIRMWARE__SYSTEM_STATUS         =                                          0x00E5
VL53L1_PAD_I2C_HV__EXTSUP_CONFIG      =                                           0x002E

cofigBlock = [0x29, 0x02, 0x10, 0x00, 0x28, 0xBC, 0x7A, 0x81, #//8
        0x80, 0x07, 0x95, 0x00, 0xED, 0xFF, 0xF7, 0xFD, #//16
        0x9E, 0x0E, 0x00, 0x10, 0x01, 0x00, 0x00, 0x00, #//24
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x34, 0x00, #//32
        0x28, 0x00, 0x0D, 0x0A, 0x00, 0x00, 0x00, 0x00, #//40
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x11, #//48
        0x02, 0x00, 0x02, 0x08, 0x00, 0x08, 0x10, 0x01, #//56
        0x01, 0x00, 0x00, 0x00, 0x00, 0xFF, 0x00, 0x02, #//64
        0x00, 0x00, 0x00, 0x00, 0x00, 0x20, 0x0B, 0x00, #//72
        0x00, 0x02, 0x0A, 0x21, 0x00, 0x00, 0x02, 0x00, #//80
        0x00, 0x00, 0x00, 0xC8, 0x00, 0x00, 0x38, 0xFF, #//88
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x91, 0x0F, #//96
        0x00, 0xA5, 0x0D, 0x00, 0x80, 0x00, 0x0C, 0x08, #//104
        0xB8, 0x00, 0x00, 0x00, 0x00, 0x0E, 0x10, 0x00, #//112
        0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x0F, #//120
        0x0D, 0x0E, 0x0E, 0x01, 0x00, 0x02, 0xC7, 0xFF, #//128
        0x8B, 0x00, 0x00, 0x00, 0x01, 0x01, 0x40 #//129 - 135 (0x81 - 0x87)
        ]

class LaserSensor(object):
    def __init__(self, modIndex,sclpin,sdapin,addr,freq):
        self.modIndex = modIndex
        self.sclpin = sclpin
        self.sdapin = sdapin
        self.i2caddr = addr
        self.freq = freq
        self._distanceMode = 0
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器

    def uninit(self):
        ret = smartSensorlib.I2CUninit(self.modIndex)   
        if ret <0 :
            raise ValueError("mod disconnect")  
    def init(self):
        # 初始化I2C
        ret = smartSensorlib.I2CInit(
            self.modIndex,
            self.sclpin,
            self.sdapin,
            16,
            self.freq,
            self.i2caddr,
        )
        if ret <0 :
            raise ValueError("mod disconnect")
    def begin(self):
      global cofigBlock
      try:
        print("start to read111")
        modelID = self.readregister16(VL53L1_IDENTIFICATION__MODEL_ID)
        
        if modelID != 0xEACC:
          return 0
        self.softReset()
        counter = 0
        while True:
            ret = self.readregister(VL53L1_FIRMWARE__SYSTEM_STATUS)
            if ret&0x01 != 0:
              break
            counter=counter+1
            if counter== 100:
              return 0
            time.sleep(0.5)
        result = self.readregister(VL53L1_PAD_I2C_HV__EXTSUP_CONFIG)
        result = (result & 0xFE) | 0x01
        self.writeregister16(VL53L1_PAD_I2C_HV__EXTSUP_CONFIG, result)
        counter = 0
        while True:
          cofigBlock[counter] = self.readregister(counter+1)
          counter = counter+1
          if counter == 36:
              break
        self.startMeasurement()
        return 1
      except Exception as e:
        raise ValueError("mod disconnect")
    def startMeasurement(self):
      global cofigBlock
      config_array = (ctypes.c_ubyte * len(cofigBlock))(*cofigBlock)
      smartSensorlib.I2CWrite(self.modIndex, 1,2, len(cofigBlock),1, config_array)
    def newDataReady(self):
      ret = self.readregister(VL53L1_GPIO__TIO_HV_STATUS)
      if ret!=0x03:
         return 1
      else:
         return 0
    def softReset(self):
      self.writeregister(VL53L1_SOFT_RESET, 0x00); 
      self.writeregister(VL53L1_SOFT_RESET, 0x01);
    def getDistance(self):
       try:
          distance = self.readregister16(VL53L1_RESULT__FINAL_CROSSTALK_CORRECTED_RANGE_MM_SD0)
          return distance
       except Exception as e:
          raise ValueError("mod disconnect")
    def getSignalRate(self):
       reading = self.readregister16(VL53L1_RESULT__PEAK_SIGNAL_COUNT_RATE_CROSSTALK_CORRECTED_MCPS_SD0)
       return reading
    def setDistanceMode(self,distanceMode):
      periodA,periodB,phaseHigh,phaseInit
      if distanceMode == 0:
        periodA = 0x07
        periodB = 0x05
        phaseHigh = 0x38;
        phaseInit = 6;
      elif distanceMode == 1:
        periodA = 0x0B;
        periodB = 0x09;
        phaseHigh = 0x78;
        phaseInit = 10;
      elif distanceMode == 2:
        periodA = 0x0F;
        periodB = 0x0D;
        phaseHigh = 0xB8;
        phaseInit = 14;
      else:
        periodA = 0x0F;
        periodB = 0x0D;
        phaseHigh = 0xB8;
        phaseInit = 14;
	    #timing
      self.writeregister(VL53L1_RANGE_CONFIG__VCSEL_PERIOD_A, periodA);
      self.writeregister(VL53L1_RANGE_CONFIG__VCSEL_PERIOD_B , periodB);
      self.writeregister(VL53L1_RANGE_CONFIG__VALID_PHASE_HIGH, phaseHigh);
	
	    #//dynamic
      self.writeregister(VL53L1_SD_CONFIG__WOI_SD0 , periodA);
      self.writeregister(VL53L1_SD_CONFIG__WOI_SD1, periodB);
      self.writeregister(VL53L1_SD_CONFIG__INITIAL_PHASE_SD0, phaseInit);
      self.writeregister(VL53L1_SD_CONFIG__INITIAL_PHASE_SD1, phaseInit);
	
      self._distanceMode = distanceMode;
      
    def getDistanceMode(self):
       return self._distanceMode
    
    def getRangeStatus(self):
        rmeasurementStatusegval = self.readregister(VL53L1_RESULT__RANGE_STATUS)
        if rmeasurementStatusegval==VL53L1_DEVICEERROR_GPHSTREAMCOUNT0READY:
            return VL53L1_RANGESTATUS_SYNCRONISATION_INT
        elif rmeasurementStatusegval==VL53L1_DEVICEERROR_RANGECOMPLETE_NO_WRAP_CHECK:
            return VL53L1_RANGESTATUS_RANGE_VALID_NO_WRAP_CHECK_FAIL
        elif rmeasurementStatusegval==VL53L1_DEVICEERROR_RANGEPHASECHECK:
          return VL53L1_RANGESTATUS_OUTOFBOUNDS_FAIL
        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_MSRCNOTARGET:
          return  VL53L1_RANGESTATUS_SIGNAL_FAIL
      
        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_SIGMATHRESHOLDCHECK:
          return VL53L1_RANGESTATUS_SIGMA_FAIL

        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_PHASECONSISTENCY:
          return  VL53L1_RANGESTATUS_WRAP_TARGET_FAIL;

        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_RANGEIGNORETHRESHOLD:
          return  VL53L1_RANGESTATUS_XTALK_SIGNAL_FAIL;

        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_MINCLIP:
          return  VL53L1_RANGESTATUS_RANGE_VALID_MIN_RANGE_CLIPPED;

        elif rmeasurementStatusegval== VL53L1_DEVICEERROR_RANGECOMPLETE:
          return  VL53L1_RANGESTATUS_RANGE_VALID;

        else:
          return  VL53L1_RANGESTATUS_NONE;
    def readregister(self,registeraddr):
        regdata = (ctypes.c_ubyte * 2)()
        ret = smartSensorlib.I2CRead(self.modIndex, registeraddr,2, 1,1, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return regdata[0]
    def readregister16(self,registeraddr):
        
        regdata = (ctypes.c_ubyte * 2)()
        ret = smartSensorlib.I2CRead(self.modIndex, registeraddr,2, 2,1, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")

        retval = regdata[0]<<8 | regdata[1]
        return retval

    def writeregister(self,registeraddr,regval):
        regdata = (ctypes.c_ubyte * 2)()
        regdata[0] = regval&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, registeraddr,2, 1,1, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return 0
    def writeregister16(self,registeraddr,regval):
        regdata = (ctypes.c_ubyte * 2)()
        regdata[0] = regval>>8
        regdata[1] = regval&0xff
        ret = smartSensorlib.I2CWrite(self.modIndex, registeraddr,2, 2,1, regdata)
        if ret < 0:
           raise ValueError("mod disconnect")
        return 0
    def send_msginfo(self, msginfo_bytes):
        packets = self.getUdpPackages(msginfo_bytes)
        for packet in packets:
            udp_socket.sendto(packet.toNetBytes(), dest_addr)

    
