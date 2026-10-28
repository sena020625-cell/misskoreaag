@echo off
chcp 65001 > nul
rem 이 파일을 작업 폴더(.env, input, output 이 있는 폴더)에 복사해 두고 더블클릭하세요.
cd /d "%~dp0"
set "PLUGIN="
for /d %%D in ("%USERPROFILE%\.claude\plugins\cache\misskorea-marketplace\misskorea\*") do set "PLUGIN=%%D"
if not defined PLUGIN (
  echo 미쓰코리아 플러그인을 찾지 못했습니다. Claude Code에서 플러그인을 먼저 설치해 주세요.
  pause
  exit /b 1
)
where python > nul 2>&1
if errorlevel 1 (
  echo Python 을 찾을 수 없습니다. Python 3.10 이상을 설치해 주세요.
  pause
  exit /b 1
)
echo 미쓰코리아 작업 화면을 시작합니다. 이 창을 닫으면 화면도 꺼집니다.
python "%PLUGIN%\app\server.py" --workdir "%~dp0"
pause
