@echo off
:: Attende che il sistema sia pronto
timeout /t 5 /nobreak > nul
:: Ripristina i processi PM2 salvati
call "C:\Users\FG\AppData\Roaming\npm\pm2.cmd" resurrect
