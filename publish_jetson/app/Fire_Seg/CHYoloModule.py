import ctypes
from ctypes import POINTER
# 导入库函数
if ctypes.sizeof(ctypes.c_voidp) == 8:
    rkYoloModule = ctypes.CDLL("./libCHYoloV5.so")
else:
    rkYoloModule = ctypes.CDLL("./libCHYoloV5.so")



#库初始化*/
#
#参数列表：
#modelPath，模型文件地址
#返回：-1：表示文件格式不合法
#      -2：表示文件不存在
#      -3: 加载模型文件失败
#      -4：初始化模型失败
#	  0：成功
#
modInit = rkYoloModule._Z7modInitPc
modInit.argtypes = [ctypes.c_char_p]
modInit.restype = ctypes.c_int

#
#读取rknnInputAttr()
#参数：无
#返回 :
#	-1:读取input，output attr num failed
#	0：成功
#
readRknnInputAndOutputAttr = rkYoloModule._Z26readRknnInputAndOutputAttrv
readRknnInputAndOutputAttr.argtypes = []
readRknnInputAndOutputAttr.restype = ctypes.c_int

#是否量化
#参数：无
#返回：
#	0：不用量化
#	1：量化
#
isQuant = rkYoloModule._Z7isQuantv
isQuant.argtypes = []
isQuant.restype = ctypes.c_int



#反初始化
uninitlib = rkYoloModule._Z9uninitlibv
uninitlib.argtypes = None
uninitlib.restype = None

#释放图片句柄
#	参数：图片句柄
#
releaseImg = rkYoloModule._Z10releaseImgPv
releaseImg.argtypes = [ctypes.c_void_p]
releaseImg.restype = None

IMAGE_FORMAT_NONE = 0
IMAGE_FORMAT_RGB888 = 1
IMAGE_FORMAT_BGR888 = 2
IMAGE_FORMAT_RGBA8888 =3
IMAGE_FORMAT_GRAY8 =4
IMAGE_FORMAT_YUV420SP_NV12=5
IMAGE_FORMAT_YUV420SP_NV21 =6

#
#    rknn_tensor_type
#
RKNN_TENSOR_FLOAT32= 0                            # data type is float32. 
RKNN_TENSOR_FLOAT16= 1                               # data type is float16. 
RKNN_TENSOR_INT8= 2                                  # data type is int8. 
RKNN_TENSOR_UINT8= 3                                 # data type is uint8. 
RKNN_TENSOR_INT16= 4                                 # data type is int16. 
RKNN_TENSOR_UINT16= 5                                # data type is uint16. 
RKNN_TENSOR_INT32= 6                                # data type is int32. 
RKNN_TENSOR_UINT32=7                                 # data type is uint32. 
RKNN_TENSOR_INT64= 8                                 # data type is int64. 
RKNN_TENSOR_BOOL=9
RKNN_TENSOR_INT4=10
RKNN_TENSOR_BFLOAT16=11

#
#rknn_tensor_format
#
RKNN_TENSOR_NCHW= 0                               # data format is NCHW. 
RKNN_TENSOR_NHWC= 1                               # data format is NHWC. 
RKNN_TENSOR_NC1HWC2=2                           # data format is NC1HWC2. 
RKNN_TENSOR_UNDEFINED=3


#
#初始化推理用到的图片
#参数：
#	modelWidth：模型定义的图片宽度
#	colorfmt：图片格式类型，推理需要用到的图像颜色格式，通常是RGB格式
#	modelHeight：模型定义的图片高度
#返回：
#	图片句柄
initInferenceImg = rkYoloModule._Z16initInferenceImgiii
initInferenceImg.argtypes = [ctypes.c_int, ctypes.c_int,ctypes.c_int]
initInferenceImg.restype = ctypes.c_void_p

#初始化letterbox,返回letterbox句柄
#	参数:无
#	返回：letterbox句柄
initLetterBox = rkYoloModule._Z13initLetterBoxv
initLetterBox.argtypes = []
initLetterBox.restype = ctypes.c_void_p


#初始化letterbox,返回letterbox句柄
#	参数:无
#	返回：letterbox句柄
configureYolov5Postprocess = rkYoloModule._Z26configureYolov5PostprocessiPKii
configureYolov5Postprocess.argtypes = [ctypes.c_int,POINTER(ctypes.c_int),ctypes.c_int]
configureYolov5Postprocess.restype = ctypes.c_int


#获取letterbox的x_pad值
#	参数:letterbox句柄
#	返回：x_pad
getLetterBoxXPad = rkYoloModule._Z16getLetterBoxXPadPv
getLetterBoxXPad.argtypes = [ctypes.c_void_p]
getLetterBoxXPad.restype = ctypes.c_float

#获取letterbox的y_pad值
#	参数:letterbox句柄
#	返回：y_pad
getLetterBoxYPad = rkYoloModule._Z16getLetterBoxYPadPv
getLetterBoxYPad.argtypes = [ctypes.c_void_p]
getLetterBoxYPad.restype = ctypes.c_float
#获取letterbox的y_pad值
#	参数:letterbox句柄
#	返回：scale
getLetterBoxScale = rkYoloModule._Z17getLetterBoxScalePv
getLetterBoxScale.argtypes = [ctypes.c_void_p]
getLetterBoxScale.restype = ctypes.c_float
#
#释放letterbox句柄
#
releaseLetterBox = rkYoloModule._Z16releaseLetterBoxPv
releaseLetterBox.argtypes = [ctypes.c_void_p]
releaseLetterBox.restype = None

#
#使用letterbox预处理图像
#参数：
#	img：原始图片数据，从文件中读取到的原始数据
#	destImg:需要用在推理的图片数据句柄，initInferenceImg函数返回值
#	letterBox:letterbox句柄
#	bgColor：颜色值，默认114
#返回：
#	-1：失败
#	0：成功
convertImageWithLetterbox = rkYoloModule._Z25convertImageWithLetterboxPvS_S_i
convertImageWithLetterbox.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
convertImageWithLetterbox.restype = ctypes.c_int

#
#获取输入属性的格式类型
#参数：attrIndex：索引
#
getInputAttrFmt = rkYoloModule._Z15getInputAttrFmti
getInputAttrFmt.argtypes = [ctypes.c_int]
getInputAttrFmt.restype = ctypes.c_int


#
#获取输入属性的维度数据
#参数：
#	attrIndex:属性索引
#	dimIndex：维度值
getInputAttrDim = rkYoloModule._Z15getInputAttrDimii
getInputAttrDim.argtypes = [ctypes.c_int,ctypes.c_int]
getInputAttrDim.restype = ctypes.c_int

#
#获取输出属性的维度数据
#参数：
#	attrIndex:属性索引
#	dimIndex：维度值
getOutputAttrDim = rkYoloModule._Z16getOutputAttrDimii
getOutputAttrDim.argtypes = [ctypes.c_int]
getOutputAttrDim.restype = ctypes.c_int

#
#获取输出属性的zp值
#参数：outputIndex:输出output的索引值
#返回值：zp
getOutputZp = rkYoloModule._Z11getOutputZpi
getOutputZp.argtypes = [ctypes.c_int]
getOutputZp.restype = ctypes.c_int

#
#获取输出属性的scale值
#参数：outputIndex:输出output的索引值
#返回值：scale
getOutputScale = rkYoloModule._Z14getOutputScalei
getOutputScale.argtypes = [ctypes.c_int]
getOutputScale.restype = ctypes.c_float
#
#	rknn input设置
#参数：
#	index：input属性的index值
#	tensortype:rknn_tensor_type
#	tensorfmt:rknn_tensor_format
#	modelWidth：模型定义的图片宽度
#	modelHeight：模型定义的图片高度
#	channel:通道数
#	inferenceImg：需要推理的图片句柄
#返回：
#	-1：表示失败
#	0：表示成功
setRknnInput = rkYoloModule._Z12setRknnInputiiiiiiPv
setRknnInput.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
setRknnInput.restype = ctypes.c_int

#
#开始rknn推理
#参数：无
#返回：
#	-1：失败
#	0：成功
startRknnRun = rkYoloModule._Z12startRknnRunv
startRknnRun.argtypes = []
startRknnRun.restype = ctypes.c_int

#
#初始化rknn输出，
#参数：
#	isQuant：是否需要量化
#返回：
#rknn output句柄
initOutputsObj = rkYoloModule._Z14initOutputsObji
initOutputsObj.argtypes = [ctypes.c_int]
initOutputsObj.restype =ctypes.c_void_p


#
#获取rknn推理结果
#参数：
#	output：output句柄
#返回：-1：表示失败
#		0：成功
getRknnOutpus = rkYoloModule._Z13getRknnOutpusPv
getRknnOutpus.argtypes = [ctypes.c_void_p]
getRknnOutpus.restype =ctypes.c_int

#
#获取index
#参数：i：索引
#返回：index
getIndexArray =rkYoloModule._Z13getIndexArrayi 
getIndexArray.argtypes = [ctypes.c_int]
getIndexArray.restype =ctypes.c_int

#获取FitlerBoxes
#参数：i：索引
#返回：
getFilterBoxes = rkYoloModule._Z14getFilterBoxesi
getFilterBoxes.argtypes = [ctypes.c_int]
getFilterBoxes.restype =ctypes.c_float
#
#获取classId
#参数：i
getClassId = rkYoloModule._Z10getClassIdi
getClassId.argtypes = [ctypes.c_int]
getClassId.restype =ctypes.c_int
#
#获取ObjProbs
#参数：i
getObjProbs = rkYoloModule._Z11getObjProbsi
getObjProbs.argtypes = [ctypes.c_int]
getObjProbs.restype =ctypes.c_float

#
#比较val大小，大于最大值，返回最大值，小于最小值，返回最小值，如果介于最大值和最小值之间，则返回val
#参数：
#	val：
#	min：最小值
#	max：最大值
clamp = rkYoloModule._Z5clampfii
clamp.argtypes = [ctypes.c_float,ctypes.c_int,ctypes.c_int]
clamp.restype =ctypes.c_int

#释放rknn output值
#参数：output
#返回：无
releaseRknnOutput = rkYoloModule._Z17releaseRknnOutputPv
releaseRknnOutput.argtypes = [ctypes.c_void_p]
releaseRknnOutput.restype =None
#
#初始化推理输出值
#参数：无
#返回：无
initProcessOutputData = rkYoloModule._Z21initProcessOutputDatav
initProcessOutputData.argtypes = []
initProcessOutputData.restype =None


#
#初始化推理输出值
#参数：无
#返回：无
StartNms = rkYoloModule._Z8StartNmsif
StartNms.argtypes = [ctypes.c_int,ctypes.c_float]
StartNms.restype =None

#
#开始i8数据处理
#参数：
#	index，output的索引
#	output：输出
#	grid_h：
#	grid_w：
#	model_in_h
#	model_in_w
#	stride
#	conf_threshold
#	zp
#	scale
StartProcessI8 = rkYoloModule._Z14StartProcessI8iPviiiiifff
StartProcessI8.argtypes = [ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.c_float,ctypes.c_float]
StartProcessI8.restype =ctypes.c_int

#
#开始float32数据处理
#参数：
#	index，output的索引
#	output：输出
#	grid_h：
#	grid_w：
#	model_in_h
#	model_in_w
#	stride
#	conf_threshold
StartProcessFp32 = rkYoloModule._Z16StartProcessFp32iPviiiiif
StartProcessFp32.argtypes = [ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_float]
StartProcessFp32.restype =ctypes.c_int

#
#获取图像大小
#参数：image：图像句柄
computeImageSize = rkYoloModule._Z16computeImageSizePv
computeImageSize.argtypes = [ctypes.c_void_p]
computeImageSize.restype =ctypes.c_int
#
#获取image的数据
#参数：
#   img:图像句柄
getImageVirtAddr = rkYoloModule._Z16getImageVirtAddrPv
getImageVirtAddr.argtypes = [ctypes.c_void_p]
getImageVirtAddr.restype =ctypes.c_char_p

#
#获取图片格式
#参数：
#   img：图片句柄
getImageFmt = rkYoloModule._Z11getImageFmtPv
getImageFmt.argtypes = [ctypes.c_void_p]
getImageFmt.restype =ctypes.c_int

#
#获取图片大小
#参数：
#   img：图片句柄
getImageSize = rkYoloModule._Z12getImageSizePv
getImageSize.argtypes = [ctypes.c_void_p]
getImageSize.restype =ctypes.c_int

#
#获取图片高度
#参数：
#   img：图片句柄
getImageHeight = rkYoloModule._Z14getImageHeightPv
getImageHeight.argtypes = [ctypes.c_void_p]
getImageHeight.restype =ctypes.c_int

#
#获取图片宽度
#参数：
#   img：图片句柄
getImageWidth = rkYoloModule._Z13getImageWidthPv
getImageWidth.argtypes = [ctypes.c_void_p]
getImageWidth.restype =ctypes.c_int

#
#写图像属性到文件
#参数：path：图像文件路径名
#	img：图像文件句柄
#返回：-1:失败
#	0：成功
writeImage = rkYoloModule._Z10writeImagePKcPv
writeImage.argtypes = [ctypes.c_char_p,ctypes.c_void_p]
writeImage.restype =ctypes.c_int

#文件中读取图像数据
#参数：
#	path：图片文件路径
#返回：
#	0：表示失败
#	其他：图像句柄
readImage = rkYoloModule._Z9readImagePKc
readImage.argtypes = [ctypes.c_char_p]
readImage.restype =ctypes.c_void_p

#从视频帧读取图像信息
#参数：
#	width:宽度
#	height：高度
#	datasize：数据长度
#	rgbformat：rgb格式
#	p:图像数据
#返回：图像句柄
getImageFromVideoFrame = rkYoloModule._Z22getImageFromVideoFrameiiiiPc
getImageFromVideoFrame.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_char_p]
getImageFromVideoFrame.restype =ctypes.c_void_p
#
#图片中画圆
#参数：
#	image：图像句柄
#	cx：中心点x坐标
#	cy：中心点y坐标
#	radius: 半径
#	color：颜色
#	thickness：线粗细
drawCircle = rkYoloModule._Z10drawCirclePviiiji
drawCircle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawCircle.restype =None

#
#图片中输入文字
#参数：
#	image：图像句柄
#	text：字符串指针
#	x：左上角x坐标
#	y：左上角y坐标
#	color：颜色
#	fontsize：文字大小
drawText = rkYoloModule._Z8drawTextPvPKciiji
drawText.argtypes = [ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawText.restype =None

#
#图片中画定向边界框
#参数：
#	image：图像句柄
#	rx：矩形中心x坐标
#	ry：矩形中心y坐标
#	rw:	矩形宽度
#	rh：矩形高度
#	angle：是相对于水平轴的旋转角度
#	color：颜色
#	thickness：线粗细
drawObbRectangle = rkYoloModule._Z16drawObbRectanglePviiiifji
drawObbRectangle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.c_uint,ctypes.c_int]
drawObbRectangle.restype =None

#
#图片中画线
#参数：
#	image：图像句柄
#	x0：起点x坐标
#	y0：起点y坐标
#	x1:	终点x坐标
#	y1：重点y坐标
#	color：颜色
#	thickness：线粗细
drawLine = rkYoloModule._Z8drawLinePviiiiji
drawLine.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawLine.restype =None

#
#图片中画矩形框
#参数：
#	image：图像句柄
#	rx：左上角x坐标
#	y0：左上角y坐标
#	rw:	宽度
#	rh：高度
#	color：颜色
#	thickness：线粗细
drawRectangle = rkYoloModule._Z13drawRectanglePviiiiji
drawRectangle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawRectangle.restype =None
