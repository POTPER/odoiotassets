import ctypes

# ����⺯��
if ctypes.sizeof(ctypes.c_voidp) == 8:
    rkYoloModule = ctypes.CDLL("./libCHFaceDetect.so")
else:
    rkYoloModule = ctypes.CDLL("./libCHFaceDetect.so")

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

#�������ģ���ʼ��
#������detectModel��ģ�͵�ַ

initDetectModel = rkYoloModule._Z15initDetectModelPc
initDetectModel.argtypes = [ctypes.c_char_p]
initDetectModel.restype = ctypes.c_int
#��ȡģ�͵Ŀ���
#��������

getDetectModelWidth = rkYoloModule._Z19getDetectModelWidthv
getDetectModelWidth.argtypes = []
getDetectModelWidth.restype = ctypes.c_int

#��ȡģ�͵ĸ߶�
#��������

getDetectModelHeight = rkYoloModule._Z20getDetectModelHeightv
getDetectModelHeight.argtypes = []
getDetectModelHeight.restype = ctypes.c_int

#��ȡģ�͵�ͨ����
getDetectModelChannel = rkYoloModule._Z21getDetectModelChannelv
getDetectModelChannel.argtypes = []
getDetectModelChannel.restype = ctypes.c_int

#��ʼ��letterbox
#��������
#���أ�letterbox���
initLetterBox = rkYoloModule._Z13initLetterBoxv
initLetterBox.argtypes = []
initLetterBox.restype = ctypes.c_void_p


#�ͷ�letterbox
#����:letterbox���

releaseLetterBox = rkYoloModule._Z16releaseLetterBoxPv
releaseLetterBox.argtypes = [ctypes.c_void_p]
releaseLetterBox.restype = None

#��ȡletterbox��x_padֵ
#	����:letterbox���
#	���أ�x_pad
getLetterBoxXPad = rkYoloModule._Z16getLetterBoxXPadPv
getLetterBoxXPad.argtypes = [ctypes.c_void_p]
getLetterBoxXPad.restype = ctypes.c_float

#��ȡletterbox��y_padֵ
#	����:letterbox���
#	���أ�y_pad
getLetterBoxYPad = rkYoloModule._Z16getLetterBoxYPadPv
getLetterBoxYPad.argtypes = [ctypes.c_void_p]
getLetterBoxYPad.restype = ctypes.c_float
#��ȡletterbox��y_padֵ
#	����:letterbox���
#	���أ�scale
getLetterBoxScale = rkYoloModule._Z17getLetterBoxScalePv
getLetterBoxScale.argtypes = [ctypes.c_void_p]
getLetterBoxScale.restype = ctypes.c_float


#��ʼ������ͼƬ
#������
#	modWidth:ģ�͵Ŀ���
#	colorfmt:ͼ�����ݸ�ʽ
#	modelHeight:ģ�͵ĸ߶�
#���أ�ͼ����

initDectectInferenceImg = rkYoloModule._Z23initDectectInferenceImgiii
initDectectInferenceImg.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int]
initDectectInferenceImg.restype = ctypes.c_void_p

#ʹ��letterboxת��ͼ��
#������img������ͼƬ
#		destImg�����ͼƬ����������ʹ��
#		letterbox��letterbox���
#		bgColor:��ɫֵ
#����ֵ��-1��ʧ��
#		  0���ɹ�

convertImageWithLetterbox = rkYoloModule._Z25convertImageWithLetterboxPvS_S_i
convertImageWithLetterbox.argtypes = [ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int]
convertImageWithLetterbox.restype = ctypes.c_int
#������������������
#������index������
#		tensortype:
#		tensorfmt:
#		modelWidth:ģ�͵Ŀ���
#		modHeight:ģ�͸߶�
#		channel:ͨ��
#		inferenceImg:����ͼƬ
#���أ�-1��ʧ��
#		0���ɹ�
setDetectRknnInput = rkYoloModule._Z18setDetectRknnInputiiiiiiPv
setDetectRknnInput.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
setDetectRknnInput.restype = ctypes.c_int


#��ʼ����
#��������
#���أ�-1��ʧ��
#		0���ɹ�

startDetectRknnRun = rkYoloModule._Z18startDetectRknnRunv
startDetectRknnRun.argtypes = []
startDetectRknnRun.restype = ctypes.c_int
#��ʼ������
#��������
#���أ�������
#
#�Ƚ�val��С���������ֵ���������ֵ��С����Сֵ��������Сֵ������������ֵ����Сֵ֮�䣬�򷵻�val
#������
#	val��
#	min����Сֵ
#	max�����ֵ
clamp = rkYoloModule._Z5clampiii
clamp.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int]
clamp.restype =ctypes.c_int

initOutputsObj = rkYoloModule._Z14initOutputsObjv
initOutputsObj.argtypes = []
initOutputsObj.restype = ctypes.c_void_p

#��ȡrknn�������
#������outputs:����������
#����ֵ��-1��ʧ��
#		  0���ɹ�

getRknnOutpus = rkYoloModule._Z13getRknnOutpusPv
getRknnOutpus.argtypes = [ctypes.c_void_p]
getRknnOutpus.restype = ctypes.c_int


#��ʼnms����
#������modelWidth��ģ�͵Ŀ���
#		modelHeight:ģ�͵ĸ߶�
#		src_img_width:ͼƬ�Ŀ���
#		src_img_height:ͼƬ�ĸ߶�
#		outputdata��output���

startDetectFilterValidAndNms = rkYoloModule._Z28startDetectFilterValidAndNmsiiiiPv
startDetectFilterValidAndNms.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_void_p]
startDetectFilterValidAndNms.restype = ctypes.c_int

#�ͷ�rknn output��Դ
#������outputs:������
#����ֵ��void

releaseRknnOutput = rkYoloModule._Z17releaseRknnOutputPv
releaseRknnOutput.argtypes = [ctypes.c_void_p]
releaseRknnOutput.restype = None
#�ͷ���Դ
#���룺��
#���أ�void

uninitlib = rkYoloModule._Z9uninitlibv
uninitlib.argtypes = []
uninitlib.restype = None

#�ͷ�ͼƬ���
#	������ͼƬ���
#
releaseImg = rkYoloModule._Z10releaseImgPv
releaseImg.argtypes = [ctypes.c_void_p]
releaseImg.restype = None

#
#��ȡͼ���С
#������image��ͼ����
computeImageSize = rkYoloModule._Z16computeImageSizePv
computeImageSize.argtypes = [ctypes.c_void_p]
computeImageSize.restype =ctypes.c_int
#
#��ȡimage������
#������
#   img:ͼ����
getImageVirtAddr = rkYoloModule._Z16getImageVirtAddrPv
getImageVirtAddr.argtypes = [ctypes.c_void_p]
getImageVirtAddr.restype =ctypes.c_char_p

#
#��ȡͼƬ��ʽ
#������
#   img��ͼƬ���
getImageFmt = rkYoloModule._Z11getImageFmtPv
getImageFmt.argtypes = [ctypes.c_void_p]
getImageFmt.restype =ctypes.c_int

#
#��ȡͼƬ��С
#������
#   img��ͼƬ���
getImageSize = rkYoloModule._Z12getImageSizePv
getImageSize.argtypes = [ctypes.c_void_p]
getImageSize.restype =ctypes.c_int

#
#��ȡͼƬ�߶�
#������
#   img��ͼƬ���
getImageHeight = rkYoloModule._Z14getImageHeightPv
getImageHeight.argtypes = [ctypes.c_void_p]
getImageHeight.restype =ctypes.c_int

#
#��ȡͼƬ����
#������
#   img��ͼƬ���
getImageWidth = rkYoloModule._Z13getImageWidthPv
getImageWidth.argtypes = [ctypes.c_void_p]
getImageWidth.restype =ctypes.c_int

#
#дͼ�����Ե��ļ�
#������path��ͼ���ļ�·����
#	img��ͼ���ļ����
#���أ�-1:ʧ��
#	0���ɹ�
writeImage = rkYoloModule._Z10writeImagePKcPv
writeImage.argtypes = [ctypes.c_char_p,ctypes.c_void_p]
writeImage.restype =ctypes.c_int

#�ļ��ж�ȡͼ������
#������
#	path��ͼƬ�ļ�·��
#���أ�
#	0����ʾʧ��
#	������ͼ����
readImage = rkYoloModule._Z9readImagePKc
readImage.argtypes = [ctypes.c_char_p]
readImage.restype =ctypes.c_void_p

#����Ƶ֡��ȡͼ����Ϣ
#������
#	width:����
#	height���߶�
#	datasize�����ݳ���
#	rgbformat��rgb��ʽ
#	p:ͼ������
#���أ�ͼ����
getImageFromVideoFrame = rkYoloModule._Z22getImageFromVideoFrameiiiiPc
getImageFromVideoFrame.argtypes = [ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_char_p]
getImageFromVideoFrame.restype =ctypes.c_void_p
#
#ͼƬ�л�Բ
#������
#	image��ͼ����
#	cx�����ĵ�x����
#	cy�����ĵ�y����
#	radius: �뾶
#	color����ɫ
#	thickness���ߴ�ϸ
drawCircle = rkYoloModule._Z10drawCirclePviiiji
drawCircle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawCircle.restype =None

#
#ͼƬ����������
#������
#	image��ͼ����
#	text���ַ���ָ��
#	x�����Ͻ�x����
#	y�����Ͻ�y����
#	color����ɫ
#	fontsize�����ִ�С
drawText = rkYoloModule._Z8drawTextPvPKciiji
drawText.argtypes = [ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawText.restype =None

#
#ͼƬ�л�����߽��
#������
#	image��ͼ����
#	rx����������x����
#	ry����������y����
#	rw:	���ο���
#	rh�����θ߶�
#	angle���������ˮƽ�����ת�Ƕ�
#	color����ɫ
#	thickness���ߴ�ϸ
drawObbRectangle = rkYoloModule._Z16drawObbRectanglePviiiifji
drawObbRectangle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_float,ctypes.c_uint,ctypes.c_int]
drawObbRectangle.restype =None

#
#ͼƬ�л���
#������
#	image��ͼ����
#	x0�����x����
#	y0�����y����
#	x1:	�յ�x����
#	y1���ص�y����
#	color����ɫ
#	thickness���ߴ�ϸ
drawLine = rkYoloModule._Z8drawLinePviiiiji
drawLine.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawLine.restype =None

#
#ͼƬ�л����ο�
#������
#	image��ͼ����
#	rx�����Ͻ�x����
#	y0�����Ͻ�y����
#	rw:	����
#	rh���߶�
#	color����ɫ
#	thickness���ߴ�ϸ
drawRectangle = rkYoloModule._Z13drawRectanglePviiiiji
drawRectangle.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_uint,ctypes.c_int]
drawRectangle.restype =None


#��ȡ���˿�ֵ
#������i������
getFilterIndicateValue = rkYoloModule._Z22getFilterIndicateValuei
getFilterIndicateValue.argtypes = [ctypes.c_int]
getFilterIndicateValue.restype =ctypes.c_int


#��ȡ����ֵ
#������i:����
#
getPropsValue = rkYoloModule._Z13getPropsValuei
getPropsValue.argtypes = [ctypes.c_int]
getPropsValue.restype =ctypes.c_float

#��ȡ����λ�ã�
#������index������

getLocations = rkYoloModule._Z12getLocationsi
getLocations.argtypes = [ctypes.c_int]
getLocations.restype =ctypes.c_float
#��ȡ���λ��
#������index������

getlandMs = rkYoloModule._Z9getlandMsi
getlandMs.argtypes = [ctypes.c_int]
getlandMs.restype =ctypes.c_float