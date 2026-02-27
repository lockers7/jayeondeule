# 스왑 크기 확인 및 늘리기 (현재 200MB → 1GB 추천)
sudo dphys-swapfile swapoff
sudo nano /etc/dphys-swapfile  # CONF_SWAPSIZE=1024 로 변경
sudo dphys-swapfile setup
sudo dphys-swapfile swapon