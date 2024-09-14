Place any git repositories in a folder called `files` to add to the dumb git http server.

Access the git repository by accessing the path to the `.git` folder, e.g. if you `git clone https://github.com/git/git` in the `files` folder, access the git repository by doing `git clone http://localhost:1000/git/.git`.

p1.zip has been provided as a sample git repository to use. Note that I have slightly modified it to duplicate the objects, copied both into the repo itself and in a packfile