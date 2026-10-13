import ctypes
import time

import numpy as np
from UdpPackage import *
import socket
import cv2
import math
from threading import Thread
from queue import Queue
from rknnlite.api import RKNNLite
from typing import List, Tuple, Optional, Dict
import os
from facedetectmod import *
from SensorModule import *

dest_addr = ('127.0.0.1', 8088)
dest_addr2 = ('127.0.0.1', 8089)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
VIS_THRESHOLD = float(os.environ.get("FACE_DETECTION_THRESHOLD", "0.50"))
MATCH_THRESHOLD = float(os.environ.get("FACE_MATCH_THRESHOLD", "0.65"))
MATCH_MARGIN = float(os.environ.get("FACE_MATCH_MARGIN", "0.06"))
MIN_FACE_SIZE = int(os.environ.get("FACE_MIN_SIZE", "48"))
GALLERY_TOP_K = int(os.environ.get("FACE_GALLERY_TOP_K", "2"))

max_packet_size = 60000
global_id = 0

# 异步发送队列
_send_queue = Queue(maxsize=3)

_send_thread = None
_send_running = False

#异步视频帧数据
_frame_queue = Queue(maxsize=3)
_parse_thread = None
_parse_video = False
_AIParseResult = []
#正在分析中
_parseing = False
#用来保存需要运算的图片句柄
inferenceImage = 0
#用来保存人脸检测需要的letterbox句柄
letter_box = 0
#人脸检测模块的人脸输入宽，高，通道数
modWidth = 0
modHeight = 0
modChannel = 0
#人脸识别类对象，在main中初始化
recognition  = None
COLOR_BLUE   =   0xFF0000
COLOR_RED   =    0x0000FF
#人员仓库，记录所有的人脸信息
personbank = []
#置信值，超过这个值，认为是同一个人
CONFIDENCE_VAL = MATCH_THRESHOLD

last_direction = 0 
_control_running=False
control_flags = 8
modules = None
_control_thread = None
#云台控制模块
ptzModIndex=17
modStatus = 0
#云台控制速度1~5
ptzSpeed = 5
OFFSET_TRED = 50

#异步AI识别视频数据
def _async_AIParse_worker():
    global _parse_video,_parseing,_AIParseResult
    while _parse_video:
        has_frame = False
        try:
            frame = _frame_queue.get(timeout=0.1)
            has_frame = True
            if frame is None:
                break
            _parseing = True
            #视频输出数据默认是BGR格式，但是推理用到的是RGB格式，所以第一步先进行格式转化
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            data_size = frame.nbytes
            #视频帧构造分析库需要的图片，并返回图片句柄
            src_img = getImageFromVideoFrame(width,height,data_size,IMAGE_FORMAT_RGB888,frame_rgb.ctypes.data_as(ctypes.c_char_p))
            #人脸检测,ret是-1表示检测失败，facenum表示检测到的人脸数，results则表示每个人脸所在区域信息
            ret,facenum,results=detect(src_img)
            
            #所有识别到的人员姓名
            detectNames=[]
            
            img0 = frame;
            releaseImg(src_img)
            _AIParseResult = []
            if ret==0 and facenum>0:
                for item in results:
                     name, similarity = identify_detection(img0, item)
                     if name is not None:
                         detectNames.append(name)
                         item.setName(name)
                         item.setSimilarty(similarity)
                     _AIParseResult.append(item)
            send_msginfo(bytes(','.join(detectNames), encoding='utf-8'))
        except Exception as exc:
            print(f"AI parse failed: {exc}")
        finally:
            _parseing = False
            if has_frame:
                _frame_queue.task_done()
#开始异步视频分析
def start_async_parsingthread():
    global _parse_thread, _parse_video
    if _parse_thread is None or not _parse_thread.is_alive():
        _parse_video = True
        print("start ai parse thread")
        _parse_thread = Thread(target=_async_AIParse_worker, daemon=True)
        _parse_thread.start()
#异步发送图片数据
def send_video_frame_async(img_bytes):
    try:
        _frame_queue.put_nowait(img_bytes)
    except:
        pass         
#异步发送数据到APP的工作线程
def _async_send_worker():
    global _send_running
    while _send_running:
        try:
            img_bytes = _send_queue.get(timeout=0.1)
            if img_bytes is None:
                break
            packets = getUdpPackages(img_bytes)
            for packet in packets:
                udp_socket.sendto(packet.toNetBytes(), dest_addr)
            _send_queue.task_done()
        except:
            pass
#开始异步发送
def start_async_sender():
    global _send_thread, _send_running
    if _send_thread is None or not _send_thread.is_alive():
        _send_running = True
        _send_thread = Thread(target=_async_send_worker, daemon=True)
        _send_thread.start()
def _async_control_worker():
    """异步控制工作线程"""
    global _control_running,last_direction,control_flags,modStatus
    last_direction = 4
    
    while _control_running:
        try:
            # 获取当前方向
            current_direction = control_flags
            # 只有方向改变时才发送命令
            if modStatus==0:
                if modules.isModReady(ptzModIndex)==1:
                    #连接
                    ret = modules.modConnect(ptzModIndex)
                    if ret == 1:
                        modStatus = 1
            if current_direction != last_direction:
                ret = modules.PtzControl(current_direction,ptzSpeed)
                if ret<0:
                    modStatus = 0
                last_direction = current_direction
            
            # 控制发送频率，避免过快发送
            time.sleep(0.05)
            
        except Exception as e:
            print(f"控制线程错误: {e}")
            time.sleep(0.1)
def start_control_thread():
    """启动控制线程"""
    global _control_thread, _control_running
    if _control_thread is None or not _control_thread.is_alive():
        _control_running = True
        _control_thread = Thread(target=_async_control_worker, daemon=True)
        _control_thread.start()
        print("控制线程已启动")

def stop_control_thread():
    """停止控制线程"""
    global _control_running
    _control_running = False
    if _control_thread:
        _control_thread.join(timeout=1)
        print("控制线程已停止") 
#停止异步发送
def stop_async_sender():
    global _send_running
    _send_running = False
    if _send_thread:
        _send_queue.put(None)
        _send_thread.join(timeout=1)
#发送消息到app，通知检测到的结果        
def send_msginfo(msginfo_bytes):
    #print( msginfo_bytes)
    packets = getUdpPackages(msginfo_bytes)
    for packet in packets:
        udp_socket.sendto(packet.toNetBytes(), dest_addr2)
#获取UDP组包
def getUdpPackages(bytes_data):
    global global_id
    global_id += 1
    packets = []
    length = len(bytes_data)
    num_packets = math.ceil(length / max_packet_size)
    for i in range(num_packets):
        start = i * max_packet_size
        end = min(start + max_packet_size, len(bytes_data))
        packet = UdpPackage(global_id, num_packets, i, end - start, bytes_data[start:end])
        packets.append(packet)
    return packets
#异步发送图片数据
def send_async(img_bytes):
    try:
        _send_queue.put_nowait(img_bytes)
    except:
        pass  
#同步发送图片数据      
def send(img_bytes):
    packets = getUdpPackages(img_bytes)
    for packet in packets:
        udp_socket.sendto(packet.toNetBytes(), dest_addr)
#根据图像数据，宽度，高度，大小，图像数据格式等，构造图像对象，直接在内存中构造，
#减少文件读取的时间
def convert_image_buffer_to_cv2(virtaddr,width,height,size,fmt):
    buffer_bytes = ctypes.string_at(virtaddr, size)
    buffer_array = np.frombuffer(buffer_bytes, dtype=np.uint8)
    img = buffer_array.reshape((height, width, 3))

    
    return img;
#人脸五个关键点位置类
class faceLandMs:
    def __init__(self,x,y):
        self.x = x
        self.y = y
#人脸识别结果
class detectResult:
    def __init__(self,left,top,right,bottom,propval):
        self.left =left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = propval
        self.landms=[]
        self.similarity = 0
        self.name = None    #检测到的人脸，后面用这个来判断是否识别到注册人员，未识别到未None
        for i in range(5):
            landms = faceLandMs(0,0)
            self.landms.append(landms)
    def setSimilarty(self,simi):
        self.similarity = simi
    def setName(self,name):
        self.name = name
    def setLandMs(self,index,x,y):
        self.landms[index].x = x
        self.landms[index].y = y
#个人档案，包括姓名，姓名是文件夹的名称，照片可能有多张，features是在多张照片中提取到的特征值
#多张照片入库，有助于提升人脸在不同角度等条件下的识别率
class person_doc:
    def __init__(self,name):
        self.name=name
        self.images=[]
        self.features=[]
        
    def addImage(self,imagepath):
        self.images.append(imagepath)
        
    def addPersonFeature(self,feature: np.ndarray):
        self.features.append(feature)

def _valid_face_crop(image: np.ndarray, result) -> Optional[np.ndarray]:
    """Reject invalid/tiny detections before feature extraction."""
    if image is None or result is None:
        return None
    height, width = image.shape[:2]
    left = max(0, min(width, int(result.left)))
    top = max(0, min(height, int(result.top)))
    right = max(0, min(width, int(result.right)))
    bottom = max(0, min(height, int(result.bottom)))
    if right - left < MIN_FACE_SIZE or bottom - top < MIN_FACE_SIZE:
        return None
    aspect_ratio = float(right - left) / float(bottom - top)
    if aspect_ratio < 0.55 or aspect_ratio > 1.80:
        return None
    return image[top:bottom, left:right]

FACE_REFERENCE_POINTS = np.array([
    [54.71, 73.85], [105.05, 73.57], [80.04, 102.48],
    [59.36, 131.95], [101.04, 131.72],
], dtype=np.float32)

def _aligned_face_crop(image: np.ndarray, result) -> Optional[np.ndarray]:
    """Align the detector's five landmarks to the FaceNet 160x160 template."""
    fallback = _valid_face_crop(image, result)
    if fallback is None or not hasattr(result, "landms") or len(result.landms) != 5:
        return fallback
    source_points = np.array([(point.x, point.y) for point in result.landms], dtype=np.float32)
    height, width = image.shape[:2]
    if (not np.all(np.isfinite(source_points)) or np.any(source_points[:, 0] < 0) or
            np.any(source_points[:, 1] < 0) or np.any(source_points[:, 0] >= width) or
            np.any(source_points[:, 1] >= height)):
        return fallback
    transform, _ = cv2.estimateAffinePartial2D(source_points, FACE_REFERENCE_POINTS, method=cv2.LMEDS)
    if transform is None:
        return fallback
    return cv2.warpAffine(image, transform, (160, 160), flags=cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE)

def identify_detection(image: np.ndarray, result) -> Tuple[Optional[str], float]:
    """Return an identity only when it is strong and distinct from alternatives."""
    face_img = _aligned_face_crop(image, result)
    if face_img is None or recognition is None:
        return None, 0.0
    feature = recognition.extract_feature(face_img)
    if feature is None:
        return None, 0.0

    candidates = []
    for person in personbank:
        scores = [recognition.compute_similarity(feature, gallery_feature)
                  for gallery_feature in person.features]
        if not scores:
            continue
        top_count = min(max(1, GALLERY_TOP_K), len(scores))
        person_score = float(np.mean(sorted(scores, reverse=True)[:top_count]))
        candidates.append((person_score, person.name))

    if not candidates:
        return None, 0.0
    candidates.sort(reverse=True)
    best_score, best_name = candidates[0]
    second_score = candidates[1][0] if len(candidates) > 1 else -1.0
    print(f"match best={best_name} score={best_score:.3f} second={second_score:.3f}")
    if best_score < MATCH_THRESHOLD or best_score - second_score < MATCH_MARGIN:
        return None, best_score
    return best_name, best_score
        
#遍历facebank目录下的人名目录下的文件，把每张人脸照片加入person的images列表
def traverse_files(directory,person):
    """遍历目录及其子目录下的所有文件"""
    for root, dirs, files in os.walk(directory):
        for file in files:
            image = os.path.join(root, file)
            person.addImage(image)
#遍历facebank目录，查找所有文件夹，每个文件夹的名称就是需要注册人员的名称
def traverse_dirs(directory):
    """遍历目录下所有文件夹"""
    personbank.clear()
    if not os.path.isdir(directory):
        print(f"facebank directory does not exist: {directory}")
        return
    for entry in sorted(os.scandir(directory), key=lambda item: item.name):
        if not entry.is_dir():
            continue
        person = person_doc(entry.name)
        traverse_files(entry.path, person)
        personbank.append(person)
            

# ==================== 人脸识别模块 ====================
class FaceRecognition:
    """FaceNet 人脸识别器"""
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.rknn_lite = RKNNLite()
        self._init_model()
    
    def _init_model(self):
        """初始化模型"""
        print(f'加载人脸识别模型: {self.model_path}')
        ret = self.rknn_lite.load_rknn(self.model_path)
        if ret != 0:
            raise RuntimeError(f'加载模型失败! ret={ret}')
        
        ret = self.rknn_lite.init_runtime()
        if ret != 0:
            raise RuntimeError(f'运行时初始化失败! ret={ret}')
        print('人脸识别模型初始化成功')
    
    def preprocess_face(self, face_img: np.ndarray, target_size: Tuple[int, int] = (160, 160)) -> np.ndarray:
        """
        预处理人脸图像
        :param face_img: BGR人脸图像
        :param target_size: 目标尺寸
        :return: 预处理后的输入数据 [1, C, H, W]
        """
        # 缩放到目标尺寸
        aligned_face = cv2.resize(face_img, target_size)
        
        # BGR 转 RGB
        aligned_face = cv2.cvtColor(aligned_face, cv2.COLOR_BGR2RGB)
        
        # 归一化到 [0, 1]
        aligned_face = aligned_face.astype(np.float32) / 255.0
        
        # 转换为 NCHW 格式
        aligned_face = np.transpose(aligned_face, (2, 0, 1))
        
        # 添加 batch 维度
        input_data = np.ascontiguousarray(np.expand_dims(aligned_face, axis=0), dtype=np.float32)
        
        return input_data
    
    def l2_normalize(self, feature: np.ndarray) -> np.ndarray:
        """L2 归一化"""
        norm = np.linalg.norm(feature)
        if norm > 1e-9:
            return feature / norm
        return feature
    
    def extract_feature(self, face_img: np.ndarray) -> Optional[np.ndarray]:
        """
        提取人脸特征
        :param face_img: BGR人脸图像
        :return: 归一化后的特征向量
        """
        if face_img is None or face_img.size == 0:
            return None
        
        input_data = self.preprocess_face(face_img)
        
        # RKNN 推理
        outputs = self.rknn_lite.inference(inputs=[input_data])
        
        if outputs is None or len(outputs) == 0:
            return None
        
        feature = outputs[0].flatten()
        if not np.all(np.isfinite(feature)):
            return None
        
        # L2 归一化
        feature = self.l2_normalize(feature)
        
        return feature
    
    def compute_similarity(self, feature1: np.ndarray, feature2: np.ndarray) -> float:
        """计算两个特征的余弦相似度"""
        if feature1 is None or feature2 is None or feature1.shape != feature2.shape:
            return -1.0
        return float(np.dot(feature1, feature2))
    
    def release(self):
        """释放资源"""
        self.rknn_lite.release()
    
def detect(src_img):
    global control_flags,last_direction
    max_face_sz = 0
    center_face_x=0
    center_face_y = 0
    #道数据
    facenum = 0;
    
    ret = convertImageWithLetterbox(src_img,inferenceImage,letter_box,114)
    
    if ret==-1:
        return -1,0,[]
    #设置inputattr
    ret = setDetectRknnInput(0,RKNN_TENSOR_UINT8,RKNN_TENSOR_NHWC,modWidth,modHeight,modChannel,inferenceImage)
    if ret == -1:
        return -1,0,[]
    #开始推理
    ret = startDetectRknnRun()
    if ret==-1:
        return -1,0,[]
    #初始化输出,参数是是否需要量化
    outputs = initOutputsObj()

    if outputs==0:
        return -1,0,[]
    #获取推理结果
    ret = getRknnOutpus(outputs)
    if ret == -1:
        releaseRknnOutput(outputs)
        return -1,0,[]
    validCount = startDetectFilterValidAndNms(modWidth,modHeight,getImageWidth(src_img),getImageHeight(src_img),outputs)
    
    result = []
    if validCount>0:
        last_count = 0;
        for j in range(validCount):
            
            if getFilterIndicateValue(j) == -1:
                continue
            if getPropsValue(j)<VIS_THRESHOLD:
                continue
            n = getFilterIndicateValue(j);
            props = getPropsValue(n)
            x1 = int(getLocations(n * 4 + 0) * modWidth - getLetterBoxXPad(letter_box))
            y1 = int(getLocations(n * 4 + 1) * modHeight - getLetterBoxYPad(letter_box))
            x2 = int(getLocations(n * 4 + 2) * modWidth - getLetterBoxXPad(letter_box))
            y2 = int(getLocations(n * 4 + 3) * modHeight - getLetterBoxYPad(letter_box))

            model_in_w = modWidth;
            model_in_h = modHeight;
            left =int( clamp(x1,0,modWidth) / getLetterBoxScale(letter_box))
            top = int(clamp(y1,0,modHeight) / getLetterBoxScale(letter_box))
            right =int( clamp(x2,0,modWidth) / getLetterBoxScale(letter_box))
            bottom =int( clamp(y2,0,modHeight) / getLetterBoxScale(letter_box))
            box = detectResult(left,top,right,bottom,props)
            facenum+=1
            if(max_face_sz<right-left):
                        max_face_sz = right-left
                        center_face_x =left+ (right-left)/2.0
                        center_face_y = top+(bottom -top)/2.0
            for k in range(5) :
                ponit_x = int(getlandMs(n * 10 + 2 * k) * modWidth - getLetterBoxXPad(letter_box));
                ponit_y = int(getlandMs(n * 10 + 2 * k + 1) * modHeight - getLetterBoxYPad(letter_box));
                x = (int)(clamp(ponit_x, 0, model_in_w) / getLetterBoxScale(letter_box));
                y = (int)(clamp(ponit_y, 0, model_in_h) / getLetterBoxScale(letter_box));
                box.setLandMs(k,x,y)
            result.append(box)
        if max_face_sz>0:
            if center_face_x - 320 >OFFSET_TRED :
                if center_face_y - 240>OFFSET_TRED:
                    #人脸在右下位置，如果云台停止状态，则控制云台朝右下运动，
                    #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=4
                    elif last_direction!=4:
                        control_flags=8
                #人脸在右上位置，如果云台停止状态，则控制云台朝右上运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                elif 240-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始转动
                        control_flags=5
                    elif last_direction!=5:
                        control_flags=8
                #人脸在右边位置，如果云台停止状态，则控制云台朝右运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                else:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=0
                    elif last_direction!=0:
                        control_flags=8    
            elif 320-center_face_x>OFFSET_TRED:
                #人脸在左下位置，如果云台停止状态，则控制云台朝左下运动，
                #如果云台处于运动状态，则先停止云台运动，等下一帧图像
                if center_face_y - 240>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=6
                    elif last_direction!=6:
                        control_flags=8
                elif 240-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=7
                    elif last_direction!=7:
                        control_flags=8
                else:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=1
                    elif last_direction!=1:
                        control_flags=8 
            else:
                if center_face_y - 240>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=3
                    elif last_direction!=3:
                        control_flags=8
                elif 240-center_face_y>OFFSET_TRED:
                    if last_direction==8:
                        #如果是停止状态，则开始云台控制
                        control_flags=2
                    elif last_direction!=2:
                        control_flags=8
                else:
                    if  last_direction!=8:
                        control_flags=8
        else:
            if  last_direction!=8:
                control_flags=8 
    releaseRknnOutput(outputs)
    return 0,facenum,result

def check_input_type(input_path):
    if input_path.endswith(('.jpg', '.png', '.jpeg', '.bmp')):
        print('Inference: ', input_path)
        src_img = readImage(input_path.encode('utf-8'))
        if src_img == 0:
            print('打开文件失败，请重试！')
            return 
        print("start to read image")
        ret,facenum,results=detect(src_img)
        print("ret="+str(ret)+"facenum="+str(facenum))
        detectNames=[]
        releaseImg(src_img)
        img0 = cv2.imread(input_path)
        
        if ret==0 and facenum>0:
            #遍历结果，
            for item in results:
                name, similarity = identify_detection(img0, item)
                if name is not None:
                    item.setSimilarty(similarity)
                #提取人脸区域
                
                #调用人脸识别模块，提取特征值
                #遍历所有人脸库，寻找分值最高的
                        #print("compare with "+person.name +" similarity is "+str(fVal))
                #最高分值超过置信值，就认为是同一个人
                    detectNames.append(name)
                    item.setName(name)
                    #print("find name "+name + " similarity is "+str(fMaxVal))
            #画框
            for item in results:
                if item.name == None:
                    for landmk in item.landms:
                        cv2.circle(img0, (int(landmk.x), int(landmk.y)), 2, (0, 255, 0), -1)
                    continue;
                # 绘制边界框
                
                cv2.rectangle(img0, (item.left, item.top), (item.right, item.bottom), COLOR_BLUE, 2)
                
                # 绘制标签背景
                label_size = cv2.getTextSize(item.name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(img0, (item.left, item.top - label_size[1] - 5), 
                            (item.left + label_size[0], item.top), COLOR_RED, -1)
                
                # 绘制标签文字
                cv2.putText(img0, item.name, (item.left, item.top - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                
                # 绘制关键点（如果有）
                for landmk in item.landms:
                    colors = [(0, 0, 255), (0, 255, 255), (255, 0, 255), (0, 255, 0), (255, 0, 0)]
                    cv2.circle(img0, (int(landmk.x), int(landmk.y)), 2, colors[0], -1)
        send_msginfo(bytes(','.join(detectNames), encoding='utf-8'))
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
        _, img_encoded = cv2.imencode('.jpg', img0, encode_params)
        send(img_encoded.tobytes())
        
        
    elif input_path == 'video':
        global _parseing,_AIParseResult
        cap = cv2.VideoCapture(41)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 减少摄像头缓冲区
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # 降低分辨率
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        #启动云台控制线程
        start_control_thread()
        # 启动异步发送线程
        start_async_sender()
        
        #启动异步ai分析线程
        start_async_parsingthread()
        
        # 帧率统计
        prev_time = time.time()
        fps = 0.0
        fps_smooth = 0.0
        
        # JPEG编码参数
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
        
        # 预热模型
        while True:
            ret, frame = cap.read()
            if not ret:
                print('无法读取摄像头帧')
                break
            if _parseing==False:
                send_video_frame_async(frame)
            print("person num ="+str(len(_AIParseResult)))
            #画框
            for item in _AIParseResult:
                if item.name == None:
                    for landmk in item.landms:
                        cv2.circle(frame, (int(landmk.x), int(landmk.y)), 2, (0, 255, 0), -1)
                    # 绘制边界框
                    cv2.rectangle(frame, (item.left, item.top), (item.right, item.bottom), COLOR_BLUE, 2)
                else:
                    # 绘制边界框
                    cv2.rectangle(frame, (item.left, item.top), (item.right, item.bottom), COLOR_BLUE, 2)
                    
                    label_txt = item.name+" {:.1f}".format(item.similarity*100)        
                    # 绘制标签背景
                    label_size = cv2.getTextSize(label_txt, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                    cv2.rectangle(frame, (item.left, item.top - label_size[1] - 5), 
                                (item.left + label_size[0], item.top), COLOR_RED, -1)
                    
                    # 绘制标签文字
                    cv2.putText(frame, label_txt, (item.left, item.top - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                    
                    # 绘制关键点（如果有）
                    for landmk in item.landms:
                        print("x="+str(landmk.x)+",y="+str(landmk.y))
                        colors = [(0, 0, 255), (0, 255, 255), (255, 0, 255), (0, 255, 0), (255, 0, 0)]
                        cv2.circle(frame, (int(landmk.x), int(landmk.y)), 2, colors[0], -1)
            # 计算实时帧率
            curr_time = time.time()
            fps = 1.0 / (curr_time - prev_time) if (curr_time - prev_time) > 0 else 0
            prev_time = curr_time
            fps_smooth = 0.9 * fps_smooth + 0.1 * fps
            
            # 在图像上显示帧率
            fps_text = f'FPS: {fps_smooth:.1f}'
            cv2.putText(frame, fps_text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2, cv2.LINE_AA)
            _, img_encoded = cv2.imencode('.jpg', frame, encode_params)
            send_async(img_encoded.tobytes())
            
            kk = cv2.waitKey(1) & 0xFF
            if kk == ord(' '):
                break
        stop_async_sender()
        cap.release()
        cv2.destroyAllWindows()
    else:
        print('输入非正确格式，重新输入！')
#从facebank文件夹中读取人脸数据
def readFaceDataInBank():
    #第一步遍历文件夹，建立人员档案
    traverse_dirs("facebank")
    #第二步，遍历每一个人
    for person in personbank:
        for image in person.images:
            #第一步检测加载人脸
            src_img = readImage(image.encode('utf-8'))
            if not src_img:
                print(f"Unable to load facebank image: {image}")
                continue
            #第二步，人脸检测
            ret,facenum,result = detect(src_img)
            if ret == -1:
                #检测不成功
                releaseImg(src_img)
                continue
            if facenum ==0:
                #未检测到人脸
                releaseImg(src_img)
                continue
            if facenum>1:
                #检测到多个人脸，忽略跳过
                releaseImg(src_img)
                continue
            releaseImg(src_img)
            image = cv2.imread(image)
            if image is None:
                continue
            face = result[0]
            face_img = _aligned_face_crop(image, face)
            if face_img is None:
                print('❌ 人脸区域无效')
                continue
            feature = recognition.extract_feature(face_img)
            if feature is not None:
                person.addPersonFeature(feature)

    for person in personbank:
        print(f"facebank identity={person.name} features={len(person.features)}")
             
if __name__ == '__main__':
    is_video = True
    model_path = './model/detect_rk3588_fp_ver01.rknn'

    # 模块初始化
    modules = SensorModule()
    # 开始搜索模块
    modules.startScanSensors()
    # 连接继电器模块
    ret = modules.modConnect(ptzModIndex)
    if ret<=0:
        print("主控模块连接失败")
    else:
        print("主控模块连接正常")
        modules.PtzControl(9,ptzSpeed)
    ret = initDetectModel(model_path.encode('utf-8'))
    if ret == -1:
        print("人脸检测模型加载失败")
    else:
        recognition = FaceRecognition("./model/facenet_mobilenet_fixed.rknn")
        if recognition ==None:
            print("人脸特征提取模型加载失败")
        else:
            modWidth = getDetectModelWidth()
            modHeight = getDetectModelHeight()
            modChannel = getDetectModelChannel()
    
            #初始化用户推理的数据数据，图像数据的格式是RGB888格式
            inferenceImage = initDectectInferenceImg(modWidth,IMAGE_FORMAT_RGB888,modHeight)
            #初始化letterbox,返回letterbox句柄
            letter_box = initLetterBox()
            #加载人脸数据
            readFaceDataInBank();
            if is_video:
                check_input_type('video')
            else:
                check_input_type("images/Penny.jpg")
            releaseLetterBox(letter_box)
            releaseImg(inferenceImage)
        uninitlib()
    stop_control_thread()
    modules.modDisconnect(ptzModIndex)
