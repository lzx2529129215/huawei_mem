#!/usr/bin/env python3
"""
Tier-2 Watermark State Watcher
Monitors /sys/kernel/debug/tier2_watermark/state every second,
exports CSV, computes user-space EWMA, and predicts time-to-watermark.
"""

import argparse
import csv
import os
import sys
import time
from collections import defaultdict

STATE_PATH = "/sys/kernel/debug/tier2_watermark/state"

class Tier2Watcher:
    def __init__(self, state_path=STATE_PATH):
        self.state_path = state_path
        self.samples = []
        self.ewma = {}  # node -> ewma_free_pages
        self.ewma_alpha = 1.0 / 16.0

    def read_state(self):
        """Parse the state file into a dict of node -> fields."""
        if not os.path.exists(self.state_path):
            return None

        with open(self.state_path, 'r') as f:
            content = f.read()

        result = {'nodes': {}}
        current_node = None
        current_zone = None

        for line in content.strip().split('\n'):
            if '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip()

            if key in ('version', 'timestamp_ns', 'enabled'):
                result[key] = val
            elif key == 'node':
                current_node = int(val)
                if current_node not in result['nodes']:
                    result['nodes'][current_node] = {'zones': {}}
            elif key == 'zone':
                current_zone = val
                if current_node is not None:
                    result['nodes'][current_node]['zones'][current_zone] = {}
            elif current_node is not None and current_zone is not None:
                result['nodes'][current_node]['zones'][current_zone][key] = val

        return result

    def update_ewma(self, node_id, free_pages):
        """Update user-space EWMA for a node."""
        if node_id not in self.ewma:
            self.ewma[node_id] = float(free_pages)
        else:
            self.ewma[node_id] = (self.ewma[node_id] * (1 - self.ewma_alpha) +
                                   float(free_pages) * self.ewma_alpha)
        return self.ewma[node_id]

    def predict_seconds(self, node_id, free_pages, target_pages):
        """Simple linear prediction: how many seconds until free_pages reaches target."""
        if node_id not in self.ewma:
            return -1
        ewma = self.ewma[node_id]
        if free_pages <= target_pages:
            return 0  # already below

        # Rate of change from EWMA
        delta = free_pages - ewma
        if delta <= 0:
            return -1  # stable or increasing, can't predict decline
        gap = free_pages - target_pages
        if delta > 0:
            return gap / delta
        return -1

    def collect_sample(self):
        """Read state and add a sample."""
        state = self.read_state()
        if state is None:
            return None

        timestamp = time.time()
        row = {
            'timestamp': timestamp,
            'enabled': state.get('enabled', '0'),
        }

        for nid_str, ndata in state.get('nodes', {}).items():
            nid = int(nid_str)
            for zname, zdata in ndata.get('zones', {}).items():
                free_pages = int(zdata.get('free_pages', 0))
                alloc_wmark = int(zdata.get('tier2_alloc_wmark', 0))
                demote_wmark = int(zdata.get('tier2_demote_wmark', 0))

                ewma = self.update_ewma(nid, free_pages)
                pred_alloc = self.predict_seconds(nid, free_pages, alloc_wmark)
                pred_demote = self.predict_seconds(nid, free_pages, demote_wmark)

                row[f'n{nid}_{zname}_free'] = free_pages
                row[f'n{nid}_{zname}_alloc_wmark'] = alloc_wmark
                row[f'n{nid}_{zname}_demote_wmark'] = demote_wmark
                row[f'n{nid}_{zname}_below_alloc'] = zdata.get('below_alloc', '0')
                row[f'n{nid}_{zname}_below_demote'] = zdata.get('below_demote', '0')
                row[f'n{nid}_{zname}_active_anon'] = zdata.get('active_anon', '0')
                row[f'n{nid}_{zname}_inactive_anon'] = zdata.get('inactive_anon', '0')
                row[f'n{nid}_{zname}_active_file'] = zdata.get('active_file', '0')
                row[f'n{nid}_{zname}_inactive_file'] = zdata.get('inactive_file', '0')
                row[f'n{nid}_{zname}_ewma_free'] = int(ewma)
                row[f'n{nid}_{zname}_pred_alloc_sec'] = pred_alloc
                row[f'n{nid}_{zname}_pred_demote_sec'] = pred_demote

        self.samples.append(row)
        return row

    def write_csv(self, filepath):
        """Write all samples to CSV."""
        if not self.samples:
            print("No samples to write")
            return

        fieldnames = self.samples[0].keys()
        with open(filepath, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(self.samples)
        print(f"Wrote {len(self.samples)} samples to {filepath}")

    def print_summary(self, row):
        """Print a one-line summary."""
        if row is None:
            return
        ts = row['timestamp']
        for key in sorted(row.keys()):
            if 'below_demote' in key and row[key] == '1':
                print(f"[{ts}] ALERT: {key} is below demote watermark!")
            if 'below_alloc' in key and row[key] == '1':
                print(f"[{ts}] WARN: {key} is below alloc watermark!")


def main():
    parser = argparse.ArgumentParser(description='Tier-2 Watermark Watcher')
    parser.add_argument('--duration', type=int, default=60,
                        help='Duration in seconds (default: 60)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='Sample interval in seconds (default: 1.0)')
    parser.add_argument('--out', default='tier2_wmark_samples.csv',
                        help='Output CSV file')
    parser.add_argument('--state-path', default=STATE_PATH,
                        help='Path to state file')
    args = parser.parse_args()

    if not os.path.exists(args.state_path):
        print(f"ERROR: state file {args.state_path} not found!")
        print("Available debugfs mounts:")
        os.system("mount | grep debugfs 2>/dev/null || echo 'No debugfs mounted'")
        sys.exit(1)

    watcher = Tier2Watcher(args.state_path)
    start = time.time()

    print(f"Monitoring {args.state_path} for {args.duration}s, interval={args.interval}s")
    print(f"Output: {args.out}")

    while time.time() - start < args.duration:
        row = watcher.collect_sample()
        if row:
            watcher.print_summary(row)
        else:
            print(f"[{time.time()}] WARNING: could not read state")

        time.sleep(args.interval)

    watcher.write_csv(args.out)
    print("Done.")


if __name__ == '__main__':
    main()
