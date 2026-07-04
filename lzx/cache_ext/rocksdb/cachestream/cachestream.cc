#include "cachestream.h"

#include <iostream>
#include <string>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
#include <sys/types.h>

namespace ROCKSDB_NAMESPACE {


int Cachestream::load_bpf_program() {
    // Initialize link to NULL to avoid cleanup issues
    link = NULL;
    
    // Get cgroup path from environment variable
    const char *cgroup_path = getenv("CGROUP_PATH");
    if (!cgroup_path) {
        fprintf(stderr, "CGROUP_PATH environment variable not set\n");
        return -1;
    }
    
    // Open cgroup directory
    cgroup_fd = open(cgroup_path, O_RDONLY);
    if (cgroup_fd < 0) {
        fprintf(stderr, "Failed to open cgroup path %s: %s (uid=%d, euid=%d)\n", 
                cgroup_path, strerror(errno), getuid(), geteuid());
        return -1;
    }
    
    // Open and load BPF skeleton
    skel = cachestream_admit_hook_bpf__open();
    if (!skel) {
        fprintf(stderr, "Failed to open BPF skeleton: %s\n", strerror(errno));
        return -1;
    }
    
    int ret = cachestream_admit_hook_bpf__load(skel);
    if (ret) {
        fprintf(stderr, "Failed to load BPF skeleton: %s\n", strerror(errno));
        cachestream_admit_hook_bpf__destroy(skel);
        skel = NULL;
        return -1;
    }
    
    // Get map fd
    map_fd = bpf_map__fd(skel->maps.bypassed_tids);
    if (map_fd < 0) {
        fprintf(stderr, "Failed to get map fd: %s\n", strerror(errno));
        cachestream_admit_hook_bpf__destroy(skel);
        skel = NULL;
        return -1;
    }
    
    // Attach cache_ext_ops to the specific cgroup
    link = bpf_map__attach_cache_ext_ops(skel->maps.admit_hook_ops, cgroup_fd);
    if (!link) {
        fprintf(stderr, "Failed to attach cache_ext_ops to cgroup: %s (errno=%d)\n", 
                strerror(errno), errno);
        close(cgroup_fd);
        cgroup_fd = -1;
        cachestream_admit_hook_bpf__destroy(skel);
        skel = NULL;
        map_fd = -1;
        return -1;
    }
    
#if DEBUG
    std::cout << "BPF program loaded and attached successfully" << std::endl;
#endif
    
    return 0;
}

Cachestream::Cachestream() {
    if (load_bpf_program() < 0) {
        std::cerr << "Failed to load BPF program, running without page cache bypass" << std::endl;
        initialized = false;
    } else {
        initialized = true;
    }
}

Cachestream::~Cachestream() {
    if (cgroup_fd >= 0) {
        close(cgroup_fd);
        cgroup_fd = -1;
    }
#ifdef BPF_DEBUG
    // Print admission statistics before cleanup
    if (initialized && skel && skel->maps.admission_stats) {
        int stats_fd = bpf_map__fd(skel->maps.admission_stats);
        if (stats_fd >= 0) {
            __u64 bypass_count = 0, normal_count = 0;
            __u32 key;
            
            // Read bypass count (key 0)
            key = 0;
            if (bpf_map_lookup_elem(stats_fd, &key, &bypass_count) == 0) {
                // Read normal count (key 1)
                key = 1;
                if (bpf_map_lookup_elem(stats_fd, &key, &normal_count) == 0) {
                    __u64 total = bypass_count + normal_count;
                    fprintf(stderr, "\n=== Cachestream Admission Statistics ===\n");
                    fprintf(stderr, "Page cache bypassed: %llu times\n", bypass_count);
                    fprintf(stderr, "Page cache used normally: %llu times\n", normal_count);
                    fprintf(stderr, "Total admissions: %llu\n", total);
                    if (total > 0) {
                        double bypass_percent = (double)bypass_count / total * 100.0;
                        fprintf(stderr, "Bypass percentage: %.2f%%\n", bypass_percent);
                    }
                    fprintf(stderr, "=====================================\n\n");
                }
            }
        }
    }
#endif

    if (link) {
        bpf_link__destroy(link);
    }
    if (skel) {
        cachestream_admit_hook_bpf__destroy(skel);
    }
}
void Cachestream::add_tgid(int tgid) {
    // noop if not initialized
    if (!initialized) {
#if DEBUG
        std::cerr << "BPF not initialized, skipping add_tgid" << std::endl;
#endif
        return;
    }


#if DEBUG
    std::cout << "adding tgid: " << tgid << std::endl;
#endif

    __u32 key = tgid;
    __u8 value = 1;
    int ret = bpf_map_update_elem(map_fd, &key, &value, BPF_ANY);
    if (ret < 0) {
        std::cerr << "bpf_map_update_elem: " << strerror(errno) << std::endl;
        std::cerr << "Failed to add tgid to map" << std::endl;
    }
}

void Cachestream::remove_tgid(int tgid) {
    // noop if not initialized
    if (!initialized) {
#if DEBUG
        std::cerr << "BPF not initialized, skipping remove_tgid" << std::endl;
#endif
        return;
    }


#if DEBUG
    std::cout << "removing tgid: " << tgid << std::endl;
#endif

    __u32 key = tgid;
    int ret = bpf_map_delete_elem(map_fd, &key);
    if (ret < 0) {
        std::cerr << "bpf_map_delete_elem: " << strerror(errno) << std::endl;
        std::cerr << "Failed to remove tgid from map" << std::endl;
    }
}

} // namespace ROCKSDB_NAMESPACE
