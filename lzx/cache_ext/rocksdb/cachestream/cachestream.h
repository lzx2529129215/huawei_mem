#pragma once

#include <unistd.h>
#include <fcntl.h>
#include <stdlib.h>
#include <stdio.h>
#include <sys/stat.h>
#include <sys/types.h>

#include <bpf/libbpf.h>
#include <bpf/bpf.h>

#include "rocksdb/rocksdb_namespace.h"
#include "cachestream/bpf/cachestream_admit_hook.skel.h"

// Set DEBUG to 1 to enable debug prints
#ifndef DEBUG
#define DEBUG 0
#endif

namespace ROCKSDB_NAMESPACE {

class Cachestream {
public:
    static Cachestream& getInstance() {
        static Cachestream instance;
        return instance;
    }

    Cachestream(const Cachestream&) = delete;
    Cachestream& operator=(const Cachestream&) = delete;

    void add_tgid(int tgid);
    void remove_tgid(int tgid);

private:
    Cachestream();
    ~Cachestream();
    int load_bpf_program();

    int map_fd = -1;
    int cgroup_fd = -1;
    struct cachestream_admit_hook_bpf *skel = NULL;
    struct bpf_link *link = NULL;
    bool initialized = false;
};

} // namespace ROCKSDB_NAMESPACE
