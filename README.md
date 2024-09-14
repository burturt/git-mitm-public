# Git MITM

This is a working implementation of a theoretical MITM attack against git cloning created by Alec Machlis. Currently, it supports MITM against GitHub (and in theory but not tested, GitLab) using the HTTP protocol. It works best on smaller repos - large repositories may take extremely long to process on the server and uses a lot of RAM to cache the objects.

As-is, the MITM attack does 2 things:
- The file `malicious.txt` is added to the root folder of the repository on the HEAD commit of the primary branch with the contents `This is not a real file in the repo`
- If a `package.json` file exists:
    - The `start` script is injected to also run `ping 1.1.1.1` at the same time as the originally listed command.
    - The additional file `ping_server.js` is created to also run `ping 1.1.1.1`, and is set to the `main` property of the `package.json`

## Requirements
- Docker and Docker Compose
- The ability to manage multiple terminals at once

## Steps to run
1. Run `docker compose up` in one terminal
2. Open 2 more terminals, one for `eve` and one for `alice`
3. Run `docker compose exec eve /bin/bash` for eve, and `docker compose exec alice /bin/bash` for alice
4. Run `./start_mitm.sh` in eve's machine
5. Verify the ARP spoofing attack worked by running `curl http://github.com` and verifying the message `MITM Success!`
6. Attempt to `git clone http://github.com/WHATEVER` on alice's machine.

