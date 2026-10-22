"""Small Android Consumer IR adapter and NEC-timing encoder."""

from dataclasses import dataclass

from kivy.utils import platform


class IrError(RuntimeError):
    pass


@dataclass
class IrDeviceInfo:
    available: bool
    label: str
    ranges: tuple = ()


def build_nec_pattern(code, repeats=0):
    """Return an alternating mark/space pattern in microseconds.

    Bytes are sent in the conventional NEC display order, each least-significant
    bit first. The RGB profile deliberately reuses NEC timing; its payload is a
    custom controller format, not a claim of universal LED-strip compatibility.
    """
    code = int(code) & 0xFFFFFFFF
    data = [
        9000, 4500,
    ]
    for byte_index in range(3, -1, -1):
        byte = (code >> (byte_index * 8)) & 0xFF
        for bit_index in range(8):
            data.extend((560, 1690 if (byte >> bit_index) & 1 else 560))
    data.append(560)
    # NEC repeat frames make many controllers more reliable when a key code is
    # configured. The Consumer IR API caps a transmitted pattern below 2 seconds.
    for _ in range(max(0, min(3, int(repeats)))):
        data.extend((40000, 9000, 2250, 560))
    if sum(data) >= 2_000_000:
        raise IrError("ИК-посылка длиннее лимита Android (2 секунды)")
    return data


def parse_key_pattern(value, repeats=1):
    """Parse a configured button value as an 8-digit NEC word or raw timings."""
    value = str(value).strip().upper()
    if value.startswith("RAW:"):
        values = value[4:].split(",")
        try:
            pattern = [int(part.strip()) for part in values]
        except ValueError:
            raise ValueError("RAW-команда должна содержать числа через запятую")
        if not 2 <= len(pattern) <= 512 or any(item <= 0 for item in pattern):
            raise ValueError("RAW-команда: нужно от 2 до 512 положительных интервалов")
        if sum(pattern) >= 2_000_000:
            raise ValueError("RAW-команда должна быть короче 2 секунд")
        return pattern
    code = value.removeprefix("0X")
    if len(code) != 8 or any(char not in "0123456789ABCDEF" for char in code):
        raise ValueError("Код кнопки должен быть 8 HEX-цифр NEC или начинаться с RAW:")
    return build_nec_pattern(int(code, 16), repeats=repeats)


class IrTransmitter:
    def __init__(self):
        self.manager = None
        self.ranges = ()
        self._error = None
        if platform != "android":
            self._error = "Запустите приложение на Android-телефоне с ИК-передатчиком"
            return
        try:
            from jnius import autoclass

            try:
                activity_class = autoclass("org.kivy.android.PythonActivity")
            except Exception:
                # Older python-for-android builds used the original package name.
                activity_class = autoclass("org.renpy.android.PythonActivity")
            activity = activity_class.mActivity
            package_manager = activity.getPackageManager()
            if not package_manager.hasSystemFeature("android.hardware.consumerir"):
                self._error = "На этом телефоне нет ИК-передатчика"
                return
            self.manager = activity.getSystemService("consumer_ir")
            if self.manager is None or not self.manager.hasIrEmitter():
                self._error = "Android не обнаружил ИК-передатчик"
                self.manager = None
                return
            try:
                supported = self.manager.getCarrierFrequencies()
                self.ranges = tuple((int(item.getMinFrequency()), int(item.getMaxFrequency())) for item in supported) if supported else ()
            except Exception:
                # Some vendor IR services report an emitter but omit its ranges.
                self.ranges = ()
        except Exception as exc:
            self.manager = None
            self._error = "Не удалось подключиться к ИК-службе Android: %s" % exc

    def inspect(self):
        if self.manager is None:
            return IrDeviceInfo(False, self._error or "ИК-передатчик недоступен", ())
        if self.ranges:
            range_text = ", ".join("%d–%d кГц" % (low // 1000, high // 1000) for low, high in self.ranges)
            label = "диапазон %s" % range_text
        else:
            label = "диапазон не указан телефоном"
        return IrDeviceInfo(True, label, self.ranges)

    def send(self, carrier_hz, pattern):
        if self.manager is None:
            raise IrError(self._error or "ИК-передатчик недоступен")
        frequency = int(carrier_hz)
        if not 30000 <= frequency <= 60000:
            raise IrError("Частота должна быть от 30000 до 60000 Гц")
        if self.ranges and not any(low <= frequency <= high for low, high in self.ranges):
            available = ", ".join("%d–%d кГц" % (low // 1000, high // 1000) for low, high in self.ranges)
            raise IrError("Телефон не поддерживает %d кГц · доступно %s" % (frequency // 1000, available))
        if not pattern or any(int(value) <= 0 for value in pattern) or sum(pattern) >= 2_000_000:
            raise IrError("ИК-посылка некорректна или длиннее 2 секунд")
        try:
            # PyJNIus converts a Python sequence to Java int[] for the typed API.
            self.manager.transmit(frequency, [int(value) for value in pattern])
        except Exception as exc:
            raise IrError("Ошибка передачи: %s" % exc)
