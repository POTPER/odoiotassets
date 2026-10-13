import ctypes
import time
from SensorModule import *
from TempHumiSensor import *
# --------------------------------------------------------------
# 系统核心功能模块

sleep_time = 1  # 设置频率为1秒
degrees_sensor_target_value = 0  # 设置目标数值
degrees_sensor_maximum_value = 0  # 设置最大数值
hectopascals_sensor_target_value = 0  # 设置目标数值
hectopascals_sensor_maximum_value = 0  # 设置最大数值
humidity_sensor_target_value = 0  # 设置目标数值
humidity_sensor_maximum_value = 0  # 设置最大数值
modIndex = 9  # 模块地址

# --------------------------------------------------------------



#模块状态，0：不在线，1：在线
modStatus = 0

def run_sensor(modules,sensor, sleep_time, send_count=0):
    global modStatus,modIndex
    #读取温湿度数据
    time.sleep(sleep_time)
    delay = sleep_time
    if modStatus==0:
        #如果传感器不在线，再查询传感器是否在线
        if modules.isModReady(modIndex)==1:
            #如果模块在线，则连接模块
             ret = modules.modConnect(modIndex)
             if ret == 1:
                #连接成功
                modStatus = 1
                #重新初始化温湿度模块
                sensor.reinit()
    
    if modStatus==1:
        #如果模块连接成功，则读取
        ret, temp, humi = sensor.readTempAndHumi()
        print("Temp      = {0:0.3f} deg C".format(temp))
        print("Humidity  = {0:0.2f} %".format(humi))
        if ret== 1:
            sensor_name = "TempHumitySensor"
            sensor_values = {"degrees_value": round(temp,2)}
            status_connection = 1
            status_communication = 1
            status_output = 1
            frequencies = str(delay) + " s/次"
            target_values = {
                "degrees value": degrees_sensor_target_value,
                "humidity value": humidity_sensor_target_value,
            }
            maximum_values = {
                "degrees value": degrees_sensor_maximum_value,
                "humidity value": humidity_sensor_maximum_value,
            }
            exceeding_limit_times = 3
            sensor.save_sensor_data_to_file(
                sensor_values,
                frequencies,
                target_values,
                maximum_values,
                exceeding_limit_times,
                sensor_name,
                status_connection,
                status_communication,
                status_output,
            )
        else:
            sensor.uninit()
            modules.modDisconnect(modIndex)
            modStatus = 0

    if modStatus==0:
        modStatus = 0
        sensor_name = "TempHumitySensor"
        sensor_values = {"degrees_value": 0}
        status_connection = 0
        status_communication = 0
        status_output = 0
        frequencies = str(delay) + " s/次"
        target_values = {
            "degrees value": degrees_sensor_target_value,
            "humidity value": humidity_sensor_target_value,
        }
        maximum_values = {
            "degrees value": degrees_sensor_maximum_value,
            "humidity value": humidity_sensor_maximum_value,
        }

        exceeding_limit_times = 3
        sensor.save_sensor_data_to_file(
            sensor_values,
            frequencies,
            target_values,
            maximum_values,
            exceeding_limit_times,
            sensor_name,
            status_connection,
            status_communication,
            status_output,
        )

    run_sensor(modules,sensor, sleep_time, send_count)


if __name__ == "__main__":
    send_count = 0

    # 模块初始化
    modules = SensorModule()
    # 开始搜索模块
    modules.startScanSensors()
    # 连接继电器模块
    ret = modules.modConnect(modIndex)

    if ret<=0:
        modStatus=0
    else:
        modStatus=1
    
    #初始化温湿度模块
    sensor = AHT20(modIndex)

    try:
        send_count = 0  # 发送计数
        # 设置传感器频率、目标值和最大值
        run_sensor(modules,sensor, sleep_time, send_count)

    except KeyboardInterrupt:
        pass

    finally:
        sensor.uninit()
        modules.modDisconnect(modIndex)
        modules.uninit()
        print(f"Total send count: {send_count}")
