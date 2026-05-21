@echo off
:: 切换到当前脚本所在的目录
cd /d %~dp0

echo [1/2] Activating virtual environment...
if not exist venv (
    echo Error: venv folder not found! Please check your directory.
    pause
    exit
)
call venv\Scripts\activate

echo [2/2] Starting WisePick API (Connecting to Supabase)...
:: 启动服务
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
 
pause