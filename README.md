One PC, two players — independent displays and input devices over Moonlight using cage, Sunshine, and Wayland virtual input injection (zwlr_virtual_pointer + zwp_virtual_keyboard).

## How to use

### 1. Launch cage
```shell
WLR_NO_HARDWARE_CURSORS=1 cage -d -- /path/to/game
```

### 2. Find the right event IDs

Sunshine creates virtual input devices once a client connects. Find them:
```shell
cat /proc/bus/input/devices | grep -E "Name|Handlers"
```

You should see something like:
```
Name="Mouse passthrough"            → event22  (relative motion + buttons)
Name="Mouse passthrough (absolute)" → event23  (absolute motion)
Name="Keyboard passthrough"         → event24  (keyboard)
```

Then pass them to the script:
```shell
python3 sunshine-input-bridge.py /dev/input/event22 /dev/input/event23 /dev/input/event24
```

### 3. (Optional) Network namespace isolation

If two instances on the same machine can't see each other over LAN due to localhost collision,
run one instance inside an isolated network namespace — see `proxyup` in the tech log.
The game will report a different local IP (`10.200.200.2`) and the two instances will discover
each other normally.

## Story: mENTAL dISORDER vs Cross-Platform LAN Gaming

Why can't Linux, Mac, and Windows see each other on the network?
Why can't a Mac Parallels Desktop VM and a Windows bare-metal machine find each other?
Why won't Linux CrossOver and macOS CrossOver connect?
The only thing that works is Linux CrossOver ↔ Linux Proton.

So — since Linux-to-Linux works, and short of slapping Asahi Linux onto the Mac, is there a
solution that leans into what Linux does best?

We have Wayland. We have Gamescope. We have Sunshine. We have Weston. We have cage.
Spin up a nested Wayland compositor, launch the game inside it. Simple enough.

Except nothing is ever simple.

**Problem 1: Sunshine x11 capture fails.**
Probably because the GPU isn't bound to the virtual display.
*Fix:* create a virtual monitor with `xrandr --addmode VIRTUAL1`, drag the cage window onto it,
point Sunshine at that output. Picture sorted. Audio is trivial — one click in KDE settings.

**Problem 2: Input devices.**
Sunshine injects a virtual mouse and keyboard into the host desktop. We need to intercept those
and redirect them into the remote session instead.

Fortunately Wayland lets us do exactly that via `zwp_virtual_keyboard_v1` and
`zwlr_virtual_pointer_v1`. With some help from Claude, we now have a Python script that grabs
Sunshine's virtual input devices and forwards all events into the nested cage session.
*(That script is what this repo is.)*

**Problem 3: localhost collision.**
Both game instances are on the same machine, so they share `127.0.0.1` and can't discover each
other over LAN. Clicking "Ready" in the lobby does nothing.

As it happens, I had a network-namespace isolation script lying around from a previous proxy
project:
```shell
#!/usr/bin/env fish
function proxyup --description 'run program in an isolated network namespace'
    if not ip netns list | grep proxified > /dev/null
        sudo ip netns add proxified
        sudo ip netns exec proxified ip addr add 127.0.0.1/8 dev lo
        sudo ip netns exec proxified ip link set lo up
        sudo ip link add proxy0 type veth peer name proxy1
        sudo ip link set proxy0 up
        sudo ip link set proxy1 netns proxified up
        sudo ip netns exec proxified ip addr add 10.200.200.2/24 dev proxy1
        sudo ip netns exec proxified ip route add default via 10.200.200.1 dev proxy1
        sudo ip addr add 10.200.200.1/24 dev proxy0
        sudo iptables -t nat -A POSTROUTING -s 10.200.200.0/24 -j MASQUERADE
        sudo mkdir -p /etc/netns/proxified
        sudo sh -c "echo 'nameserver 1.1.1.1' > /etc/netns/proxified/resolv.conf"
        sudo iptables -A FORWARD -i proxy0 -j ACCEPT
        sudo iptables -t filter -A FORWARD -m state ! --state NEW -o proxy0 -j ACCEPT
    end
    sudo -E ip netns exec proxified su -p leohearts -c "$argv"
end
```
```shell
proxyup bash   # fish crashes inside the namespace for some reason, bash works fine
```

Launch Wine as usual from inside the namespace. The game now reports its local IP as
`10.200.200.2`, the two instances see each other as separate hosts, and the lobby works.

![Image](https://github.com/user-attachments/assets/9d155ce8-ae79-4e04-aed9-ea63d604647c)
