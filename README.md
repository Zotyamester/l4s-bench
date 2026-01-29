# l4s-bench

A Mininet-based testbench for measuring L4S's performance.

## Prerequisites

As of now, the recommended way of running the script is by using prebuilt Vagrant box, the only dependency of the project is Vagrant itself (and an arbitrary provider supported by Vagrant).

In the future, when both DualPI2 and TCP Prague will be ubiquitously available in the mainline Linux kernel, Vagrant will no longer be needed (except if installing Mininet locally is too much burden). At that time, the dependency becomes [Mininet](https://github.com/mininet/mininet).

## Usage

After downloading [`l4s.box`](https://bmeedu-my.sharepoint.com/:u:/g/personal/szatmary_zoltan_edu_bme_hu/IQBzAk4vykv_TYXP64hmmWTbAY0Xt-6WQHuBKiQvUooVtY8), add it to Vagrant:

```bash
vagrant box add l4s l4s.box
```


Spin up Vagrant:

```bash
vagrant up
```

Connect to the VM:

```bash
vagrant ssh
```

Run the script:

```bash
sudo /vagrant/net.py
```