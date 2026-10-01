@echo off
rem 彩票分析助手 - 一键构建 APK（Windows）
rem 优先使用 gradlew；没有则用本机 gradle 生成 wrapper 再构建；都没有则提示用 Android Studio
chcp 65001 >nul
cd /d "%~dp0"

if exist gradlew.bat goto :build

where gradle >nul 2>nul
if errorlevel 1 (
  echo 未找到 Gradle 命令，也缺少 gradlew 包装器。
  echo.
  echo 推荐方式：用 Android Studio 打开本目录（android\），等待 Gradle 同步完成后：
  echo   菜单 Build -^> Build App Bundle^(s^)/APK^(s^) -^> Build APK^(s^)
  echo 生成的 APK 位于 app\build\outputs\apk\debug\app-debug.apk
  echo.
  echo 或者安装 Gradle 8.7+ 后重新双击本脚本。
  pause
  exit /b 1
)

echo 生成 Gradle Wrapper（8.7）...
call gradle wrapper --gradle-version 8.7 --distribution-type bin
if errorlevel 1 goto :fail

:build
echo 开始构建 Debug APK（首次需联网下载依赖，耗时较长）...
call gradlew.bat assembleDebug --stacktrace
if errorlevel 1 goto :fail

if exist app\build\outputs\apk\debug\app-debug.apk (
  echo.
  echo ============================================
  echo  构建成功！APK 位置：
  echo  %cd%\app\build\outputs\apk\debug\app-debug.apk
  echo ============================================
) else (
  echo [警告] 构建结束但未找到 APK 产物，请查看上方日志。
)
pause
goto :eof

:fail
echo.
echo [失败] 构建未完成，请把上方错误信息反馈给开发者。
pause
