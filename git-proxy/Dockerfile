FROM python:3.12

WORKDIR /app

# ENV TZ=Europe/Rome
# RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y iptables tcpdump dsniff iproute2 python3 python3-pip tmux dnsutils sudo wget curl nodejs npm net-tools
# RUN pip3 install scapy mitmproxy --break-system-packages

COPY requirements.txt /app/
RUN pip3 install -r requirements.txt --break-system-packages
COPY . /app

CMD uvicorn app:app --host 0.0.0.0 --port 8080 --reload --reload-dir /app
