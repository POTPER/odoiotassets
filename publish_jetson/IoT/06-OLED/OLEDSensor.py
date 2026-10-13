import ctypes
import time
import socket
import os
import json
import math
from PIL import Image
import numpy as np

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


# 屏幕初始化
# 参数1：模块地址
# 参数2：SCL pin 序号
# 参数3：SDA PIN 序号

smartSensorlib.LCDSsd1306Init.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int
]
smartSensorlib.LCDSsd1306Init.restype = ctypes.c_int


# LCD屏反初始化
# 参数1：模块地址

smartSensorlib.LCDSsd1306UnInit.argtypes = [
    ctypes.c_int
]
smartSensorlib.LCDSsd1306UnInit.restype = ctypes.c_int

# LCD屏测试
# 参数1：模块地址

smartSensorlib.LCDSsd1306Test.argtypes = [
    ctypes.c_int
]
smartSensorlib.LCDSsd1306Test.restype = ctypes.c_int

# LCD屏画bitmap
# 参数1：模块地址
# 参数2：左上角x坐标
# 参数3：左上角y坐标
# 参数4：宽度w
# 参数5：高度h
# 参数4：一维lcd数据,大小w*h/8
smartSensorlib.LCDSsd1306Drawbitmap.argtypes = [
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.POINTER(ctypes.c_ubyte),
]
smartSensorlib.LCDSsd1306Drawbitmap.restype = ctypes.c_int


class SSD1306Lcd(object):
    def __init__(self, modIndex,scl,sda):
        self.modIndex = modIndex
        self.scl = scl
        self.sda = sda
        # 继电器模块放在第五个模块位置，判断第5个模块位置的传感器状态，如果模块在线，则控制模块的继电器

        print("start to read init aht20 mod")
        # 初始化
        ret = smartSensorlib.LCDSsd1306Init(self.modIndex,self.scl,self.sda)
        if ret <0 :
            raise ValueError("mod disconnect")
    def reinit(self):
        ret = smartSensorlib.LCDSsd1306Init(self.modIndex,self.scl,self.sda)
        if ret <0 :
            raise ValueError("mod disconnect")
    def uninit(self):
       ret = smartSensorlib.LCDSsd1306UnInit(self.modIndex)
       if ret <0 :
            raise ValueError("mod disconnect")

    def testLcd(self):
        ret = smartSensorlib.LCDSsd1306Test(self.modIndex)
        if ret <0 :
            raise ValueError("mod disconnect")
    def image_to_ssd1306_buffer(self,image, width, height):
        """
        将 BMP 图片转换为 SSD1306 可用的 C 数组
        
        Args:
            image_path: BMP 图片路径
            width: 屏幕宽度（默认 128）
            height: 屏幕高度（默认 64）
        
        Returns:
            bytearray: 转换后的像素数据
        """
        # 1. 打开图片并缩放到目标尺寸
        img = image.convert('L')  # 转换为灰度
        #img = img.resize((width, height), Image.Resampling.LANCZOS)
        img = img.resize((width, height), Image.LANCZOS)
        # 2. 二值化处理（阈值 127）
        # 大于 127 的像素设为 255（白色），否则为 0（黑色）
        img_binary = img.point(lambda p: 255 if p > 127 else 0, '1')
        
        # 3. 转换为 numpy 数组（0-255 范围）
        pixels = np.array(img_binary, dtype=np.uint8)
        # 将白色（255）转为 1，黑色（0）保持 0
        pixels = (pixels > 0).astype(np.uint8)
        
        # 4. 转换为 SSD1306 的页寻址格式
        # 屏幕分为 height/8 = 8 页，每页有 width 个字节
        # 每个字节的 8 个 bit 代表一列的 8 个像素
        buffer = bytearray(width * (height // 8))
        
        for y in range(height):
            for x in range(width):
                if pixels[y, x] == 1:  # 白色像素需要点亮
                    page = y // 8          # 计算属于哪个页
                    bit = y % 8            # 计算在该页中的哪一位
                    # SSD1306 的位顺序：bit7 = 顶部像素
                    buffer[page * width + x] |= (1 << bit)
        
        return buffer
    def drawBitmap(self,x,y,w,h,image):
        """
        在 OLED 屏幕上显示 PIL Image 图像
        
        Args:
            x: 左上角 x 坐标
            y: 左上角 y 坐标
            image: PIL Image 对象
        """
        width, height = image.size
        buffer = self.image_to_ssd1306_buffer(image, width, height)
        # 转换为 ctypes 数组
        buffer_array = (ctypes.c_ubyte * len(buffer))(*buffer)
        smartSensorlib.LCDSsd1306Drawbitmap(
            self.modIndex, x, y, width, height, buffer_array
        )
