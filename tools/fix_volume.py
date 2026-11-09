"""把当前处于 Active 状态的播放设备设为 100% 且取消静音（测试后恢复用）。"""
from pycaw.pycaw import AudioUtilities


def main():
    for d in AudioUtilities.GetAllDevices():
        try:
            if "Active" not in str(d.state):
                continue
            v = d.EndpointVolume
            v.SetMute(0, None)
            v.SetMasterVolumeLevelScalar(1.0, None)
            print("OK", d.FriendlyName, "vol=100 mute=0")
        except Exception as e:  # noqa: BLE001
            continue


if __name__ == "__main__":
    main()
