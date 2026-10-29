#!/usr/bin/env python3
"""V5独立静态诊断：不导入旧Demo1、不加载原厂驱动、不启动设备。"""

import importlib.util
import logging
import sys
from pathlib import Path


def main():
    logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    try:
        for name in ('light_teaching_support.py', 'UdpPackage.py', 'BRICS2026_Final_Sample_Light.py',
                     'BRICS2026_Final_Sample_Light_anser.py'):
            path = root / name
            compile(path.read_text(encoding='utf-8-sig'), str(path), 'exec')
        from light_teaching_support import check_environment
        for name in ('BRICS2026_Final_Sample_Light', 'BRICS2026_Final_Sample_Light_anser'):
            path = root / (name + '.py')
            spec = importlib.util.spec_from_file_location(name, path)
            entry = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(entry)
            check_environment(entry.experiment_info, entry.teaching_config(), path)
            logging.info('%s：静态检查通过', name)
        logging.info('检查完成；未验证动态库兼容性、实物型号、模块连接和实际光照读数。')
        return 0
    except Exception as exc:
        logging.error('检查失败：%s', exc)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
