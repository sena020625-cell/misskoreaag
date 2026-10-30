@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo 미쓰코리아 작업 화면을 시작합니다. 이 창을 닫으면 화면도 꺼집니다.
where python > nul 2>&1
if errorlevel 1 (
  where py > nul 2>&1
  if errorlevel 1 (
    echo Python 을 찾을 수 없습니다. Python 3.10 이상을 설치해 주세요.
    pause
    exit /b 1
  )
  py -3 app\server.py %*
) else (
  python app\server.py %*
)
pause
