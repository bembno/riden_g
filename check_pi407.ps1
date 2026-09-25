$password = 'raspberry'
$sshCmd = "ssh -o ConnectTimeout=10 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no pi@192.168.2.42 'screen -ls; ps aux | grep -E \"bms_mqtt|mosquitto\" | grep -v grep'"

$proc = Start-Process ssh -ArgumentList "-o ConnectTimeout=10 -o StrictHostKeyChecking=no -o PubkeyAuthentication=no pi@192.168.2.42 'screen -ls; ps aux | grep -E bms_mqtt | grep -v grep'" -RedirectStandardInput "C:\git_hub\riden_g\pass.txt" -Wait -PassThru