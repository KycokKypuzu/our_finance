from models.device import Device


class DeviceDomain:
    @staticmethod
    def get_all_devices(raw_devices: list[dict]) -> list[Device]:
        return [Device.model_validate(device) for device in raw_devices]

    @staticmethod
    def get_device_by_id(raw_devices: list[dict], device_id: str) -> Device | None:
        for device in DeviceDomain.get_all_devices(raw_devices):
            if device.id == device_id:
                return device
        return None
