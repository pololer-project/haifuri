@echo off
setlocal enabledelayedexpansion

:: Create fonts directory if it doesn't exist
if not exist "fonts" mkdir "fonts"

echo Moving font files to 'fonts' folder...
for /d %%D in (*_Attachments) do (
    if exist "%%D\*.ttf" (
        echo Found .ttf in %%D
        move "%%D\*.ttf" "fonts\"
    )
    if exist "%%D\*.otf" (
        echo Found .otf in %%D
        move "%%D\*.otf" "fonts\"
    )
)

echo.
echo Renaming subtitle files...
powershell -NoProfile -Command "Get-ChildItem -Filter '*.ass' | ForEach-Object { if ($_.Name -match 'High School Fleet - ([A-Za-z0-9]+)') { $newName = $matches[1] + '.ass'; Write-Host 'Renaming' $_.Name 'to' $newName; Rename-Item -LiteralPath $_.FullName -NewName $newName -ErrorAction SilentlyContinue } }"

echo.
echo Operation complete.
pause
