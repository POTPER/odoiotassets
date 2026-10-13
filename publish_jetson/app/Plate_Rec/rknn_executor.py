from  rknnlite.api import RKNNLite as RKNN


#   NPU_CORE_AUTO  = 0          default, run on NPU core randomly.
#   NPU_CORE_0     = 1          run on NPU core 0.
#   NPU_CORE_1     = 2          run on NPU core 1.
#   NPU_CORE_2     = 4          run on NPU core 2.
#   NPU_CORE_0_1   = 3          run on NPU core 1 and core 2.
#   NPU_CORE_0_1_2 = 7          run on NPU core 1 and core 2 and core 3.
#   NPU_CORE_ALL   = 0xffff     run on all NPU cores.       

class RKNN_model_container():
    def __init__(self, model_path,nup_core) -> None:
        self.rknn = RKNN()

        ret = self.rknn.load_rknn(model_path)
        if ret != 0:
            self.rknn = None
            raise RuntimeError(f"加载 RKNN 模型失败: {model_path}, error={ret}")

        print('--> 开始初始化运行时环境')

        ret = None
        
        if nup_core == 0:
            ret = self.rknn.init_runtime(core_mask=RKNN.NPU_CORE_0)
        elif nup_core == 1:
            ret = self.rknn.init_runtime(core_mask=RKNN.NPU_CORE_1)
        elif nup_core == 2:
            ret = self.rknn.init_runtime(core_mask=RKNN.NPU_CORE_2)
        else:
            ret = self.rknn.init_runtime(core_mask=RKNN.NPU_CORE_ALL)
        
        if ret != 0:
            print(f'--> 初始化运行时环境失败,请检查模型路径是否正确{model_path}')
            self.rknn.release()
            self.rknn = None
            raise RuntimeError(f"初始化 RKNN 运行环境失败: error={ret}")
        print('--> 初始化运行时环境成功')

    def __del__(self):
        self.release()

    def run(self, inputs):
        if self.rknn is None:
            print("ERROR: rknn 已经被释放release")
            return []

        if isinstance(inputs, list) or isinstance(inputs, tuple):
            pass
        else:
            inputs = [inputs]

        result = self.rknn.inference(inputs=inputs)
    
        return result

    def release(self):
        if self.rknn is not None:
            self.rknn.release()
            self.rknn = None
