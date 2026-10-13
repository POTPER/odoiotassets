import ctypes
import time

import numpy as np
from UdpPackage import *
import socket
import cv2
import math
from threading import Thread
from queue import Queue
from CHYoloModule import *
from SensorModule import *

BOX_THRESH = 0.25
NMS_THRESH = 0.45
CONFIDENCE_VAL = 0.5
COLOR_BLUE   =   0xFF0000
COLOR_RED   =    0x0000FF

dest_addr = ('127.0.0.1', 8088)
dest_addr2 = ('127.0.0.1', 8089)
udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


max_packet_size = 60000
global_id = 0
#异步视频帧数据
_frame_queue = Queue(maxsize=3)
_parse_thread = None
_parse_video = False
_AIParseResult = []
#正在分析中
_parseing = False

# 异步发送队列
_send_queue = Queue(maxsize=3)
_send_thread = None
_send_running = False

destImage = 0
letter_box = 0

modWidth = 0
modHeight = 0
modChannel = 0
bQuant = 0  
last_direction = 0 
_control_running=False
control_flags = 8
modules = None
_control_thread = None
#云台控制模块
ptzModIndex=17
modStatus = 0
#云台控制速度1~5
ptzSpeed = 1
OFFSET_TRED = 50
#人脸识别结果
class detectResult:
    def __init__(self,left,top,right,bottom,propval,id):
        self.left =left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = propval
        if id == 0:
            self.name='Fire'+"{:.1f}".format(self.prop*100)
       
        self.id = id
        
#异步AI识别视频数据
def _async_AIParse_worker():
    global _parse_video,_parseing,_AIParseResult
    while _parse_video:
        try:
            frame = _frame_queue.get(timeout=0.1)
            if frame is None:
                break
            _parseing = True
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame.shape
            data_size = frame.nbytes
            src_img = getImageFromVideoFrame(width,height,data_size,IMAGE_FORMAT_RGB888,frame_rgb.ctypes.data_as(ctypes.c_char_p))
            ret,firenum,results=detect(src_img)
            releaseImg(src_img)
            _AIParseResult=[]
            if ret == 0:
                for item in results:
                    _AIParseResult.append(item)
            if firenum==0:
                send_msginfo(bytes("无",encoding='utf-8'))
            else:
                send_msginfo(bytes("有",encoding='utf-8'))
            _parseing = False
            _frame_queue.task_done()
        except:
            pass
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
                    #连接温湿度模块
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

def start_async_sender():
    global _send_thread, _send_running
    if _send_thread is None or not _send_thread.is_alive():
        _send_running = True
        _send_thread = Thread(target=_async_send_worker, daemon=True)
        _send_thread.start()

def stop_async_sender():
    global _send_running
    _send_running = False
    if _send_thread:
        _send_queue.put(None)
        _send_thread.join(timeout=1)
        
def send_msginfo(msginfo_bytes):
    print( msginfo_bytes)
    packets = getUdpPackages(msginfo_bytes)
    for packet in packets:
        udp_socket.sendto(packet.toNetBytes(), dest_addr2)
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

class detResultBox:
    def __init__(self, left, top,right,bottom,prop,cls_id):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom
        self.prop = prop
        self.cls_id = cls_id
def send_async(img_bytes):
    try:
        _send_queue.put_nowait(img_bytes)
    except:
        pass        
def send(img_bytes):
    packets = getUdpPackages(img_bytes)
    for packet in packets:
        udp_socket.sendto(packet.toNetBytes(), dest_addr)
def convert_image_buffer_to_cv2(virtaddr,width,height,size,fmt):
    print("convert_image_buffer_to_cv2 width="+str(width)+"height="+str(height)+"size="+str(size))
    buffer_bytes = ctypes.string_at(virtaddr, size)
    buffer_array = np.frombuffer(buffer_bytes, dtype=np.uint8)
    img = buffer_array.reshape((height, width, 3))
    if fmt == IMAGE_FORMAT_RGB888:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    else:
        raise ValueError(f"Unsupported image format: {fmt}")
    img = img.copy()
    return img;
def detect(src_img):
    max_face_sz = 0
    center_face_x=0
    center_face_y = 0
    #数据
    firenum = 0;
    ret = convertImageWithLetterbox(src_img,destImage,letter_box,114)
    if ret==-1:
        return -1,0,[]
    #设置inputattr
    ret = setRknnInput(0,RKNN_TENSOR_UINT8,RKNN_TENSOR_NHWC,modWidth,modHeight,modChannel,destImage)
    if ret == -1:
        return -1,0,[]
    #开始推理
    ret = startRknnRun()
    if ret==-1:
        return -1,0,[]
    #初始化输出,参数是是否需要量化
    outputs = initOutputsObj(bQuant)
    if outputs==0:
        return -1,0,[]
    #获取推理结果
    ret = getRknnOutpus(outputs)
    if ret == -1:
        return -1,0,[]
    validCount = 0
    initProcessOutputData();
    result = []
    for i in range(3):
        zp = getOutputZp(i)
        scale = getOutputScale(i)
        grid_h = getOutputAttrDim(i,2)
        grid_w = getOutputAttrDim(i,3)
        stride = int(modWidth / grid_h)
        if bQuant == 0:
            validCount+=StartProcessFp32(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH)
        else:
            validCount+=StartProcessI8(i,outputs,grid_h,grid_w,modHeight,modWidth,stride,BOX_THRESH,zp,scale)
    StartNms(validCount,NMS_THRESH)
    if validCount>0:
        for j in range(validCount):
            
            if getIndexArray(j) == -1:
                continue
            n = getIndexArray(j);
            id = getClassId(n)
            
            x1 = getFilterBoxes(n * 4 + 0) - getLetterBoxXPad(letter_box)
            y1 = getFilterBoxes(n * 4 + 1) - getLetterBoxYPad(letter_box)
            x2 = x1 + getFilterBoxes(n * 4 + 2)
            y2 = y1 + getFilterBoxes(n * 4 + 3)
            obj_conf = getObjProbs(j)
            left =int( clamp(x1,0,modWidth) / getLetterBoxScale(letter_box))
            top = int(clamp(y1,0,modHeight) / getLetterBoxScale(letter_box))
            right =int( clamp(x2,0,modWidth) / getLetterBoxScale(letter_box))
            bottom =int( clamp(y2,0,modHeight) / getLetterBoxScale(letter_box))
            if obj_conf>CONFIDENCE_VAL:
                print("find fire")
                if id == 0:
                    if(max_face_sz<right-left):
                        max_face_sz = right-left
                        center_face_x =left+ (right-left)/2.0
                        center_face_y = top+(bottom -top)/2.0
                    result.append(detectResult(left,top,right,bottom,obj_conf,id))
                    firenum+=1
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
    return 0,firenum,result
def initYoloModel(model_path):
    ret = modInit(model_path.encode('utf-8'))
    if ret != 0:
        print("mod init failed")
        return -1;
    readRknnInputAndOutputAttr()
    ret = configureYolov5Postprocess(1, None, 0)
    if ret != 0:
        uninitlib()
        print("configureYolov5Postprocess ret="+str(ret))
        raise RuntimeError(f"postprocess config failed: {ret}")       
    return ret
def uninitYolodModel():
    return uninitlib()    
def check_input_type(input_path):
    if input_path.endswith(('.jpg', '.png', '.jpeg', '.bmp')):
        print('Inference: ', input_path)
        src_img = readImage(input_path.encode('utf-8'))
        if src_img == 0:
            print('打开文件失败，请重试！')
            return -1,0,0
        ret,firenum,results=detect(src_img)
        releaseImg(src_img)
        
        img0 = cv2.imread(input_path)
        if ret == 0:
            for item in results:
                cv2.rectangle(img0, (item.left, item.top), (item.right, item.bottom), COLOR_BLUE, 2)
                label_size = cv2.getTextSize(item.name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(img0, (item.left, item.top - label_size[1] - 5), 
                        (item.left + label_size[0], item.top), COLOR_RED, -1)
                # 绘制标签文字
                cv2.putText(img0, item.name, (item.left, item.top - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        if firenum==0:
            send_msginfo(bytes("无",encoding='utf-8'))
        else:
            send_msginfo(bytes("有",encoding='utf-8'))
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 70]
        _, img_encoded = cv2.imencode('.jpg', img0, encode_params)
        send(img_encoded.tobytes())
        
        
    elif input_path == 'video':
        global _parseing,_AIParseResult
        cap = cv2.VideoCapture(41)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # 减少摄像头缓冲区
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # 降低分辨率
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        start_control_thread()
        # 启动异步发送线程
        start_async_sender()
        #启动异步AI视频分析
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
            for item in _AIParseResult:
                cv2.rectangle(frame, (item.left, item.top), (item.right, item.bottom), COLOR_BLUE, 2)
                label_size = cv2.getTextSize(item.name, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
                cv2.rectangle(frame, (item.left, item.top - label_size[1] - 5), 
                        (item.left + label_size[0], item.top), COLOR_RED, -1)
                # 绘制标签文字
                cv2.putText(frame, item.name, (item.left, item.top - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
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

if __name__ == '__main__':
    is_video = True
    img_path = 'testimg/fire1.jpg'
    model_path = './model/fire_rk3588_fp_v2.rknn'
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
    initYoloModel(model_path)
    fmt = getInputAttrFmt(0)
    if fmt == RKNN_TENSOR_NCHW:
        #model is NCHW input fmt
        modWidth = getInputAttrDim(0,3)
        modHeight = getInputAttrDim(0,2)
        modChannel = getInputAttrDim(0,1)
    else:
        #model is NHWC input fmt
        modWidth = getInputAttrDim(0,2)
        modHeight = getInputAttrDim(0,1)
        modChannel = getInputAttrDim(0,3)
    bQuant = isQuant()
    #初始化用户推理的数据数据，图像数据的格式是RGB888格式
    destImage = initInferenceImg(modWidth,IMAGE_FORMAT_RGB888,modHeight)
    #初始化letterbox,返回letterbox句柄
    letter_box = initLetterBox()
    if is_video:
        check_input_type('video')
    else:
        check_input_type(img_path)
    releaseLetterBox(letter_box)
    releaseImg(destImage)
    uninitYolodModel()
    stop_control_thread()
    modules.modDisconnect(ptzModIndex)