@echo off
echo === Обновление Chimera Bot ===
cd C:\chimera_bot
git pull origin master
C:\nssm\nssm-2.24\win64\nssm.exe restart chimera_bot
echo === Бот обновлён и перезапущен ===
pause
