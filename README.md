In Portainer → Stacks → Add stack → Repository

<strong>Repository URL:</strong> dein Git-Repo

<strong>Repository reference:</strong> z. B. main

<strong>Compose path:</strong> docker-compose.yml

Deploy.

Portainer zieht den Code und baut das Image anhand des Dockerfile (sofern der Portainer-Endpoint Bauen unterstützt – bei “Docker Standalone” i. d. R. ja, bei Swarm-Umgebungen ggf. auf dem Manager).


2 Services werden gestartet:

reminder-main (http://<IP>:5000)

und reminder-kiosk (http://<IP>:5001)


ACHTUNG:

Diese software hat <strong>KEINERLEI</strong> sicherheits features. Man kann sich in die App Einloggen, allein mit dem Benuternamen. Auch ist weder der Server noch die Application gehärtet. Diese software sollte NUR local betrieben werden und darf nicht exponiert werden!
