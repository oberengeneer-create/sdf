# LumaIR

Kivy-приложение-пульт для RGB-ленты с точным выбором цвета и передачей через Android Consumer IR.

## Возможности

- Цветовое колесо, точный ввод HEX `#RRGGBB` и RGB `0–255`, отдельная яркость.
- Быстрые оттенки и до 12 сохранённых цветов.
- Два профиля передачи: настраиваемый экспериментальный RGB-пакет `[адрес, R, G, B]` и таблица кнопочных NEC/RAW-команд.
- Команды включения и выключения по кодам из таблицы профиля.
- Проверка наличия ИК-передатчика и поддерживаемой частоты телефона.
- Настройки и избранное хранятся локально в приватной папке приложения; интернет-разрешение не требуется.

## Совместимость с контроллером

У LED-контроллеров нет общего формата для произвольных RGB-цветов. Многие комплектные пульты передают отдельные команды для фиксированного набора оттенков. Для таких контроллеров выберите профиль «Коды кнопок / RAW» и внесите реальные коды кнопок в таблицу. Точный цвет можно передать только если контроллер принимает RGB-пакет или для этого оттенка есть соответствующая команда в таблице.

RGB-профиль формирует 32-битный кадр с NEC-таймингами и данными `[адрес, R, G, B]`. Это экспериментальный формат, а не стандарт для всех LED-лент. Используйте его, если документация контроллера подтверждает такой формат. Частоту, обычно начинаемую с 38 кГц, можно менять в настройках; приложение сравнивает её с диапазоном, сообщённым Android.

Для RAW-кнопки введите чередующиеся длительности импульсов/пауз в микросекундах, начиная с импульса, например:

```text
RAW:9000,4500,560,560,560,1690,560,560
```

Телефон должен иметь встроенный ИК-передатчик. ИК-приёмник, камера или вспышка его не заменяют. У приложения нет ИК-приёмника, поэтому оно не может считать сигнал комплектного пульта; коды нужно взять из документации или определить отдельным приёмником.

Пример таблицы в настройках (коды здесь демонстрационные):

```json
{
  "#FF3048": "20DF10EF",
  "#34D9A2": "RAW:9000,4500,560,560,560,1690,560,560",
  "POWER_OFF": "20DF40BF"
}
```

Ключ — точный цвет `#RRGGBB` или действие `POWER_ON`, `POWER_OFF`, `WHITE`; значение — восьмизначный NEC-код либо RAW-тайминги. Для профиля NEC введите обычный полный 32-битный код в HEX, например `20DF10EF`.

## Сборка APK в Windows через WSL2

Buildozer собирает Android-приложение в Linux. При необходимости установите WSL2 с Ubuntu из PowerShell:

```powershell
wsl --install -d Ubuntu-24.04
```

Откройте Ubuntu, скопируйте каталог проекта в файловую систему Linux WSL и перейдите туда. Затем установите зависимости:

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip python3-venv \
  autoconf automake autopoint libtool libltdl-dev pkg-config zlib1g-dev \
  libncurses5-dev libncursesw5-dev \
  libtinfo6 cmake libffi-dev libssl-dev gettext
curl https://sh.rustup.rs -sSf | sh
source "$HOME/.cargo/env"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools buildozer cython==0.29.34
chmod +x build_apk.sh
./build_apk.sh
```

Первый запуск загрузит Android SDK/NDK. Debug APK появится в `bin/`. Для установки по USB после подключения телефона с включённой USB-отладкой выполните `buildozer android debug deploy run`.

## Файлы проекта

- `main.py` — Kivy-интерфейс, цветовой ввод, избранное и экран профилей.
- `ir_backend.py` — Android Consumer IR, кодировщик NEC и проверка RAW-посылок.
- `buildozer.spec` — разрешение `TRANSMIT_IR`, параметры APK и зафиксированный коммит python-for-android с исправлением ошибки pip.
- `profiles.sample.json` — минимальный пример профиля.
- `build_apk.sh` — запуск debug-сборки Buildozer.

## Запуск на компьютере для проверки интерфейса

На Windows откройте PowerShell в распакованной папке `ir_led_remote` и выполните:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip setuptools
.\.venv\Scripts\python.exe -m pip install "kivy[base]"
.\.venv\Scripts\python.exe main.py
```

Откроется desktop-предпросмотр: можно проверить экран, колесо оттенков, ввод HEX/RGB и избранное. На компьютере нет Android Consumer IR, поэтому отправка команд работать не будет; статус покажет режим предпросмотра.

## Сборка APK через GitHub Actions

Workflow находится в `.github/workflows/android.yml` и собирает APK напрямую на чистом GitHub-hosted `ubuntu-24.04` runner. Docker-образ стороннего Buildozer Action больше не используется, поэтому ошибочный Launchpad PPA из этого образа не попадает в сборку. В списке пакетов есть `libltdl-dev`: рецепт `libffi` в python-for-android использует предоставляемый им макрос `LT_SYS_SYMBOL_USCORE`. В `buildozer.spec` python-for-android закреплён на upstream-коммите с исправлениями ошибок обновления pip и установки Android wheels, включая `charset_normalizer`. Чтобы запустить workflow:

1. Создайте пустой репозиторий GitHub и отправьте туда **содержимое** папки `ir_led_remote` вместе со скрытой папкой `.github`.
2. При отправке в ветку `main` GitHub автоматически начнёт сборку. Её также можно вручную запустить во вкладке **Actions → Build Android APK → Run workflow**.
3. Откройте завершившийся запуск и скачайте `LumaIR-debug-apk` в разделе **Artifacts**. APK находится внутри скачанного архива.

Можно отправить файлы командой Git из PowerShell, находясь в папке проекта:

```powershell
git init
git add .
git commit -m "Add LumaIR"
git branch -M main
git remote add origin https://github.com/ВАШ_АККАУНТ/lumair.git
git push -u origin main
```

GitHub Actions собирает отладочный APK, который подходит для установки на телефон; для публикации в магазине потребуется отдельная release-сборка и подпись собственным ключом. Workflow устанавливает системные зависимости и Buildozer непосредственно на Linux runner, затем прикладывает `bin/*.apk` к запуску как artifact. Первый запуск может занять больше времени, потому что Buildozer скачивает Android SDK и NDK.
