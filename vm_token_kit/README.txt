=== Получение VK Kate-токена на Ubuntu 22.04 (через git-репозиторий) ===

0) Клонируй репозиторий с кодом бота на ВМ:

   - публичный репозиторий:
       git clone https://github.com/USER/REPO.git && cd REPO

   - приватный по SSH (сначала ключ ВМ добавить в аккаунт GitHub):
       ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
       cat ~/.ssh/id_ed25519.pub        # добавить на GitHub -> Settings -> SSH keys
       git clone git@github.com:USER/REPO.git && cd REPO

   - приватный по HTTPS (попросит логин и Personal Access Token вместо пароля)

1) Поставь системные пакеты (один раз):
     sudo apt update
     sudo apt install -y python3-venv git

2) Создай окружение и поставь зависимости кита:
     cd vm_token_kit
     python3 -m venv venv
     venv/bin/pip install -r requirements.txt

3) Запусти скрипт:
     venv/bin/python get_token.py

   Он спросит логин/пароль выделенного аккаунта ВК (ввод скрыт),
   при 2FA — код. В конце напечатает три строки:
     VK_TOKEN=...
     VK_USER_AGENT=...
     VK_API_VERSION=...

4) Скопируй эти три строки в .env основной машины (Windows),
   заменив соответствующие строки, и перезапусти там бота.

Если в репозитории нет папки vm_token_kit — добавь её с основной машины:
     git add vm_token_kit && git commit -m "vm token kit" && git push

Заметки:
- Пароль нигде не сохраняется; после успеха ВМ можно удалить.
- result.env с токеном НЕ коммитить обратно в репозиторий (он в .gitignore).
- Если ВК потребует подтвердить вход в браузере — пришли полный вывод.
