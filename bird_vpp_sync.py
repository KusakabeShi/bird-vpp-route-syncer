#!/usr/bin/python3
import os
import sys
import re
import subprocess
import fnmatch
from vpp_papi import VPPApiJSONFiles
from vpp_papi import vpp_papi
import ipaddress
import pdb
CLIENT_ID = "VppPythonClient"
VPP_JSON_DIR = '/usr/share/vpp/api/core/'
API_FILE_SUFFIX = '*.api.json'

interface_name = sys.argv[1]

def load_json_api_files(json_dir=VPP_JSON_DIR, suffix=API_FILE_SUFFIX):
    jsonfiles = []
    for root, dirnames, filenames in os.walk(json_dir):
        for filename in fnmatch.filter(filenames, suffix):
            jsonfiles.append(os.path.join(json_dir, filename))

    if not jsonfiles:
        print('Error: no json api files found')
        exit(-1)

    return jsonfiles


def connect_vpp(jsonfiles):
    vpp = vpp_papi.VPPApiClient(apifiles=jsonfiles)
    r = vpp.connect("CLIENT_ID")
    print("VPP api opened with code: %s" % r)
    return vpp

def bird_get_table(table):
    birdret = subprocess.run(["birdc","show","route","table",table,"primary","all"], timeout=3,capture_output=True)
    aaa = birdret.stdout.decode("utf8")
    route_list = re.split('\\n(?!\\t)', aaa)
    route_parsed = {}
    for index,item in enumerate(route_list):
        if "AS" not in item:
            continue
        route_attr = {}
        nexthop = ""
        for detail in item.split("\n"):
            if detail.startswith("\t"):
                if ":" in detail and "[" not in detail:
                    attr_key , attr_val = detail.split(":",1)
                    route_attr[attr_key[1:]] = attr_val[1:].split(" ")
            elif "AS" in detail:
                nexthop = ipaddress.ip_network(detail.split(" ")[0])
            else:
                print(item)
                print(detail)
        prefix = ipaddress. ip_address(route_attr["BGP.next_hop"][0])
        route_parsed[nexthop] = prefix
    return route_parsed

def ip_route_add_del(vpp,sw_if_index,is_add,prefix,nexthop):
    if type(nexthop) == ipaddress.IPv4Address:
        ip_f = "ip4"
        ip_len=32
    elif type(nexthop) == ipaddress.IPv6Address:
        ip_f = "ip6"
        ip_len=128
    else:
        raise Exception("Not support nexthop type")
    action = "add" if is_add else "del"
    print(" ".join(["vppctl","ip","route",action,str(prefix),"via",str(nexthop)]))
    subprocess.run(["vppctl","ip","route",action,str(prefix),"via",str(nexthop)], timeout=3,capture_output=True)
    return
    # I want to use VPPAPI, but it's buggy for ipv6 address
    lstack = [{} for _ in range(16)]
    if ip_f == "ip4":
        vpp.api.ip_route_add_del(
            is_add=is_add,
            route={
                "table_id": 0,
                "prefix": prefix,
                "n_paths": 1,
                "paths": [
                    {
                        "sw_if_index": sw_if_index,
                        "table_id": 0,
                        "nh": {
                            "address": {ip_f: nexthop},
                            "obj_id": sw_if_index,
                        },
                        "label_stack": lstack,
                    }
                ],
            },
        )

def main():
    bird_route = {}
    vpp_route = {"ip4":{},"ip6":{}}
    try:
        bird_route["ip4"] = bird_get_table("master4")
#         print(bird_route["ipv4"])
        bird_route["ip6"] = bird_get_table("master6")
#         print(bird_route["ipv6"])
    except subprocess.TimeoutExpired as e:
        svret = subprocess.run(["sv", "force-restart","bird"])
        return
    vpp = connect_vpp(load_json_api_files())
    for r in vpp.api.ip_route_dump(table= { 'table_id': 0, 'is_ip6': False }):
        prefix = r.route.prefix
        nexthop = r.route.paths[0].nh.address.ip4
        if nexthop == ipaddress. ip_address('0.0.0.0'):
            continue
        if nexthop in prefix and prefix.prefixlen == 32:
            continue
        vpp_route["ip4"][prefix] = nexthop
    for r in vpp.api.ip_route_dump(table= { 'table_id': 0, 'is_ip6': True }):
        prefix = r.route.prefix
        nexthop = r.route.paths[0].nh.address.ip6
        if nexthop == ipaddress. ip_address('::'):
            continue
        if nexthop in prefix and prefix.prefixlen == 128:
            continue
        vpp_route["ip6"][prefix] = nexthop
#         print( r.route.paths[0].nh.address)
    vpp_r4_to_del = dict(vpp_route["ip4"].items() - bird_route["ip4"].items())
    vpp_r4_to_add = dict(bird_route["ip4"].items() - vpp_route["ip4"].items())
    vpp_r6_to_del = dict(vpp_route["ip6"].items() - bird_route["ip6"].items())
    vpp_r6_to_add = dict(bird_route["ip6"].items() - vpp_route["ip6"].items())
    sw_if_index = 0
    for intf in vpp.api.sw_interface_dump():
        if intf.interface_name == interface_name:
            sw_if_index=intf.sw_if_index
    
    for prefix,nexthop in vpp_r4_to_del.items():
        ip_route_add_del(vpp,sw_if_index,False,prefix,nexthop)
    for prefix,nexthop in vpp_r6_to_del.items():
        ip_route_add_del(vpp,sw_if_index,False,prefix,nexthop)
    for prefix,nexthop in vpp_r4_to_add.items():
        ip_route_add_del(vpp,sw_if_index,True,prefix,nexthop)
    for prefix,nexthop in vpp_r6_to_add.items():
        ip_route_add_del(vpp,sw_if_index,True,prefix,nexthop)
        
main()
