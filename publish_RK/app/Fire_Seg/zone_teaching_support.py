"""V20 drawing and teaching support; retains the original four-input rule API.

Hardware is owned by the lazy buzzer worker. Importing opens no device.
"""

import time
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from teaching_support import BuzzerLink, ExperimentLog, TeachingSession, LOG

SOUND_NAMES = {'silent':'静音', 'alarm':'警报音', 'notice':'提示音1', 'notice2':'提示音2'}
SOUND_PATTERNS = {'silent':(1,.1,.1,1.), 'alarm':(3,.15,.10,.50),
                  'notice':(1,.25,0.,1.50), 'notice2':(2,.15,.15,1.50)}


def validate_display(config):
    names=config['REGION_NAMES']
    if not isinstance(names,(list,tuple)) or len(names)!=3 or any(not isinstance(s,str) or not s.strip() for s in names):
        raise ValueError('REGION_NAMES必须为三个非空区域名称，按左、中、右排列。')
    if len(set(names))!=3:
        raise ValueError('三个区域名称不能重复，避免授权对应错误。')
    colors=config.get('REGION_COLORS')
    if not isinstance(colors,(tuple,list)) or len(colors)!=3:
        raise ValueError('REGION_COLORS必须按左、中、右提供三个BGR颜色，请同步配套模块。')
    for key,value in zip(('COLOR_REBAR_AREA','COLOR_TEMPORARY_WORK_AREA','COLOR_MATERIAL_AREA'),colors):
        if not isinstance(value,(tuple,list)) or len(value)!=3 or any(type(x) is not int or not 0<=x<=255 for x in value):
            raise ValueError('{}必须是三个0..255整数的BGR颜色。'.format(key))
    for key in ('REGION_TEXT_COLOR','COLOR_FIRE_HIGH','COLOR_FIRE_LOW',
                'BRIGHT_LABEL_TEXT','DARK_LABEL_TEXT','STATS_TEXT_COLOR'):
        value=config[key]
        if not isinstance(value,(list,tuple)) or len(value)!=3 or any(type(x) is not int or not 0<=x<=255 for x in value):
            raise ValueError('{}必须是三个0..255整数的BGR颜色。'.format(key))
    for key in ('REGION_LINE_WIDTH','REGION_FONT_SIZE','REGION_STATUS_FONT_SIZE'):
        if type(config[key]) is not int or config[key]<=0:
            raise ValueError('{}必须为正整数。'.format(key))
    if type(config['REGION_BOTTOM_MARGIN']) is not int or config['REGION_BOTTOM_MARGIN']<0:
        raise ValueError('REGION_BOTTOM_MARGIN必须为非负整数。')
    if any(type(config[key]) is not bool for key in ('SHOW_REGIONS','SHOW_AUTH_STATUS','SHOW_STATS','PERMIT_VALID')):
        raise ValueError('画面显示开关与permit_valid必须为布尔值。')
    for key in ('AUTH_STATUS_POSITION','STATS_POSITION'):
        value=config[key]
        if not isinstance(value,(list,tuple)) or len(value)!=2 or any(type(x) is not int or x<0 for x in value):
            raise ValueError('{}必须是两个非负整数的画面坐标。'.format(key))


def reference_mode(material, rebar, temporary_work, permit):
    # 固定任务规则，供针对性验证使用；不会用它替学生填写CSV。
    if material>0: return 'alarm'
    if rebar>0 and not permit: return 'notice'
    if temporary_work>0: return 'notice2'
    return 'silent'


@dataclass(frozen=True)
class PermitState:
    valid: bool
    remaining: int
    text: str


class PermitWindow:
    """One authorization per run; snapshot starts the countdown once."""
    def __init__(self, enabled, duration):
        if type(enabled) is not bool:
            raise ValueError('permit_valid必须为True或False。')
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<=0:
            raise ValueError('PERMIT_DURATION必须为有限正数，单位秒。')
        self.enabled, self.duration = enabled, duration
        self.deadline = None

    def snapshot(self, now=None):
        now = time.monotonic() if now is None else now
        if not self.enabled:
            return PermitState(False,0,'动火未授权')
        if self.deadline is None:
            self.deadline = now+self.duration
        remaining = max(0,math.ceil(self.deadline-now))
        if remaining == 0:
            return PermitState(False,0,'动火授权已到期')
        return PermitState(True,remaining,'动火授权有效：剩余{}秒'.format(remaining))


class ZoneCommands:
    def __init__(self): self.clear()
    def clear(self): self.calls,self.mode=0,None
    def _set(self,mode): self.calls+=1; self.mode=mode
    def alarm(self): self._set('alarm')
    def notice(self): self._set('notice')
    def notice2(self): self._set('notice2')
    def reset(self): self._set('silent')


class ZoneOverlay:
    def __init__(self,font_path,display):
        validate_display(display)
        self.font_path=Path(font_path).resolve()
        if not self.font_path.is_file():
            raise ValueError('缺少指定中文字体：{}，请整体复制V20部署包。'.format(self.font_path))
        try:
            from PIL import ImageFont
        except ImportError as exc:
            raise RuntimeError('中文绘制需要Pillow：python3 -m pip install -r requirements.txt') from exc
        self.config={**display,'REGION_NAMES':tuple(display['REGION_NAMES'])}
        ImageFont.truetype(str(self.font_path),24)
        self._layer(720,405,display['PERMIT_VALID'])

    @staticmethod
    def _text_bbox(draw,text,font):
        measure=getattr(draw,'textbbox',None)
        if callable(measure): return measure((0,0),text,font=font)
        measure=getattr(font,'getbbox',None)
        if callable(measure): return measure(text)
        measure=getattr(draw,'textsize',None)
        if callable(measure): width,height=measure(text,font=font)
        else:
            measure=getattr(font,'getsize',None)
            if not callable(measure): raise RuntimeError('Pillow缺少可用的文字测量接口。')
            width,height=measure(text)
        offset=getattr(font,'getoffset',None)
        left,top=offset(text) if callable(offset) else (0,0)
        return left,top,width,height

    @lru_cache(maxsize=4)
    def _layer(self,width,height,permit,status=None):
        from PIL import Image,ImageDraw,ImageFont
        c=self.config
        image=Image.new('RGBA',(width,height),(0,0,0,0))
        draw=ImageDraw.Draw(image)
        cuts=(0,width//3,2*width//3,width)
        rgba=lambda bgr:tuple(reversed(bgr))+(255,)
        self.last_label_bounds=[]
        if c['SHOW_REGIONS']:
            for index,name in enumerate(c['REGION_NAMES']):
                left,right=cuts[index],cuts[index+1]
                color=c['REGION_COLORS'][index]
                draw.rectangle((left+1,1,right-2,height-2),outline=rgba(color),width=c['REGION_LINE_WIDTH'])
                size=max(1,min(c['REGION_FONT_SIZE'],round(height*.07),(right-left-8)//len(name)))
                font=ImageFont.truetype(str(self.font_path),size)
                bbox=self._text_bbox(draw,name,font)
                tw,th=bbox[2]-bbox[0],bbox[3]-bbox[1]
                margin=min(c['REGION_BOTTOM_MARGIN'],max(2,height//5))
                x=(left+right-1-tw)/2-bbox[0]
                y=max(2,height-margin-th)-bbox[1]
                draw.rectangle((max(left+2,int(x+bbox[0])-4),int(y+bbox[1])-3,
                                min(right-2,int(x+bbox[2])+4),min(height-2,int(y+bbox[3])+3)),fill=rgba(color))
                brightness=.114*color[0]+.587*color[1]+.299*color[2]
                text_color=c['BRIGHT_LABEL_TEXT'] if brightness>=128 else c['DARK_LABEL_TEXT']
                draw.text((x,y),name,font=font,fill=rgba(text_color))
                self.last_label_bounds.append((name,(x+bbox[0],y+bbox[1],x+bbox[2],y+bbox[3])))
        if c['SHOW_AUTH_STATUS']:
            region='钢筋加工区'
            status=status if status is not None else (region+'：授权待计时' if permit else '动火未授权')
            font=ImageFont.truetype(str(self.font_path),max(1,min(c['REGION_STATUS_FONT_SIZE'],(width-12)//len(status))))
            bbox=self._text_bbox(draw,status,font)
            x,y=c['AUTH_STATUS_POSITION']
            x=min(x,max(0,width-(bbox[2]-bbox[0])-2))-bbox[0]
            y=min(y,max(0,height-(bbox[3]-bbox[1])-2))-bbox[1]
            draw.text((x,y),status,font=font,fill=rgba(c['REGION_TEXT_COLOR']),
                      stroke_width=1,stroke_fill=(0,0,0,255))
        image=np.asarray(image)
        return np.ascontiguousarray(image[:,:,:3][:,:,::-1]),np.ascontiguousarray(image[:,:,3])

    def apply(self,frame,permit,status=None):
        import cv2
        if type(permit) is not bool: raise ValueError('permit_valid必须为True或False。')
        h,w=frame.shape[:2]
        if h<32 or w<24: raise ValueError('三区画面要求宽>=24、高>=32。')
        color,mask=self._layer(w,h,permit,status)
        cv2.copyTo(color,mask,frame)
        return frame


class ZoneLog(ExperimentLog):
    # 四个独立记录槽，钢筋区的两个时段互不覆盖；不在记录器内判定学生答案对错。
    SCENES=('材料区','钢筋区（授权有效）','钢筋区（授权到期）','临时作业区')
    METADATA_COLUMNS=('考试编号','项目名称','监测点位')
    COLUMNS=('施工区域','区域颜色（BGR）','是否识别到火焰','授权状态','是否警报','警报类型')

    def _empty_row(self,scene):
        index=self.SCENES.index(scene)
        color=self.config['DISPLAY']['REGION_COLORS'][(2,0,0,1)[index]]
        return {**self.metadata,'施工区域':('材料区','钢筋区','钢筋区','临时作业区')[index],
                '区域颜色（BGR）':str(tuple(color)),
                '是否识别到火焰':'未验证','授权状态':'不适用' if index==0 else '未验证',
                '是否警报':'未验证','警报类型':'未验证'}

    def _save(self):
        import csv
        # 写入三项考试信息及六项配色/观察结果，共九列；后台维护的设备状态和内部数量均不进入主表。
        fields=[*self.METADATA_COLUMNS,*self.COLUMNS]
        temporary=self.path.with_suffix('.csv.tmp')
        with temporary.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fields)
            writer.writeheader()
            writer.writerows({key:self._safe_cell(row.get(key,'')) for key in fields}
                             for row in self.rows.values())
        temporary.replace(self.path)

    def _sample(self,data):
        mode,now=data.get('mode'),data['now']
        counts=(data.get('material',0),data.get('work',0),data.get('outside',0))
        # 没有高分火焰时无法推断卡片位置；多区场景也无法归因，均保持未测项目原状。
        if mode not in SOUND_NAMES or sum(count>0 for count in counts)!=1:
            self._candidate=self._since=self._last=None
            return
        material,rebar,temporary_work=counts
        permit=data.get('permit')
        if type(permit) is not bool:
            self._candidate=self._since=self._last=None
            return
        if material:
            scene,authorization=self.SCENES[0],'不适用'
        elif rebar:
            scene=self.SCENES[1] if permit else self.SCENES[2]
            authorization='有效' if permit else '已到期'
        else:
            scene,authorization=self.SCENES[3],'未授权'
        candidate=(scene,mode)
        if (candidate!=self._candidate or self._last is None or now<=self._last
                or now-self._last>self.config['RESULT_TIMEOUT']):
            self._candidate,self._since=candidate,now
        self._last=now
        if now-self._since+1e-9<self.config['CONFIRM_TIME']:
            return
        # 直接记录学生函数实际提交的请求；即使错报、漏报、类型错误，也如实保留。
        self.rows[scene].update({'是否识别到火焰':'是','授权状态':authorization,
                                '是否警报':'否' if mode=='silent' else '是',
                                '警报类型':SOUND_NAMES[mode]})


class ZoneBuzzer(BuzzerLink):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._mode='silent'
    def update(self,mode,now):
        if mode not in SOUND_PATTERNS: raise ValueError('未知声音模式：{}'.format(mode))
        with self._lock:
            if self._mode!=mode: self._condition=False
            self._mode=mode
        super().update(mode!='silent',now)
    def _pattern(self): return SOUND_PATTERNS[self._mode]


class ZoneSession(TeachingSession):
    LOG_CLASS=ZoneLog
    BUZZER_CLASS=ZoneBuzzer

    def update_regions(self,material,rebar,temporary_work,low,permit,now=None):
        now=time.monotonic() if now is None else now
        mode=None
        if not self._disabled:
            try:
                if type(permit) is not bool: raise ValueError('permit_valid必须为True或False。')
                self.commands.clear()
                self.rule(material,rebar,temporary_work,permit)
                if self.commands.calls!=1 or self.commands.mode not in SOUND_NAMES:
                    raise ValueError('每次必须且只能调用一个声音接口或reset()。')
                mode=self.commands.mode
            except Exception as exc:
                self._disabled=True
                self.log.submit('error',action='区域联动判断',error=str(exc))
                self.log.submit('device',status='联动停用：判断函数异常')
                self.stop()
                LOG.exception('判断异常，联动停用，识别继续运行')
        if self.buzzer is not None and mode is not None: self.buzzer.update(mode,now)
        state=(material,rebar,temporary_work,low,permit,mode)
        if state!=self._last_state or self._last_record is None or now-self._last_record>=min(.25,self.config['CONFIRM_TIME']):
            self.log.submit('sample',material=material,work=rebar,outside=temporary_work,low=low,permit=permit,mode=mode,now=now)
            self._last_state,self._last_record=state,now
