import asyncio
import sys

# --- 修复 Python 3.12+ 的事件循环问题 ---
try:
    asyncio.get_event_loop()
except RuntimeError:
    # 如果当前没有事件循环，则手动创建一个并设置为当前循环
    asyncio.set_event_loop(asyncio.new_event_loop())

# 现在可以安全地导入 ib_insync 了
from ib_insync import *

# 确保 Windows 上的输出编码正确
import io
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 创建 IB 实例
ib = IB()

try:
    print("--- 正在尝试连接 TWS ---")
    # 尝试连接 TWS (127.0.0.1 代表本机，7497 是模拟盘端口)
    # clientId 设置为 999 避免与正式交易脚本冲突
    ib.connect('127.0.0.1', 7497, clientId=999)

    print("✅ 连接成功！")
    print("--- 正在获取账户信息 ---")
    
    # 获取账户摘要
    summary = ib.accountSummary()
    
    found = False
    for p in summary:
        if p.tag == 'NetLiquidation':
            print(f"💰 当前账户总值 (NetLiquidation): {p.value} {p.currency}")
            found = True
            break
            
    if not found:
        print("⚠️ 已连接但未获取到资产摘要，请检查 TWS 是否已完成登录。")

except Exception as e:
    print(f"❌ 连接失败！错误原因: {e}")
    print("\n请检查：")
    print("1. TWS 是否已经打开并登录（红色图标是模拟盘）？")
    print("2. TWS 设置中的 '启用ActiveX和套接字客户端' 是否勾选？")
    print("3. 端口号是否为 7497？")

finally:
    # 无论成功失败，最后都要断开连接释放端口
    if ib.isConnected():
        ib.disconnect()
        print("--- 连接已安全关闭 ---")