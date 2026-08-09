#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <sys/stat.h>
#include <sys/time.h>

#define MAX_VMAS 200000
#define LINE_BUF 8192
#define COPY_BUF 65536

typedef struct {
    unsigned long start, end, offset, inode;
    char perms[16], dev[64], pathname[4096], region_type[64];
    long rss_kb, pss_kb, referenced_kb, anonymous_kb, swap_kb;
    long shared_clean_kb, shared_dirty_kb, private_clean_kb, private_dirty_kb;
    long locked_kb;
    char vm_flags[1024];
} VMA;

static long long now_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (long long)tv.tv_sec * 1000LL + tv.tv_usec / 1000;
}

static void ensure_dir(const char *dir) {
    mkdir(dir, 0755);
}

static int file_exists(const char *p) {
    return access(p, F_OK) == 0;
}

static void csv_escape(FILE *f, const char *s) {
    if (!s) { fputc(',', f); return; }
    int need = 0;
    for (const char *p=s; *p; ++p)
        if (*p==',' || *p=='"' || *p=='\n' || *p=='\r') need = 1;
    if (!need) {
        fputs(s, f);
        return;
    }
    fputc('"', f);
    for (const char *p=s; *p; ++p) {
        if (*p=='"') fputc('"', f);
        if (*p!='\n' && *p!='\r') fputc(*p, f);
    }
    fputc('"', f);
}

static void append_temp_to_file(const char *tmp_path, const char *dest_path) {
    FILE *src = fopen(tmp_path, "r");
    if (!src) return;
    FILE *dest = fopen(dest_path, "a");
    if (!dest) { fclose(src); return; }
    char *buf = (char *)malloc(COPY_BUF);
    if (!buf) { fclose(src); fclose(dest); return; }
    size_t n;
    while ((n = fread(buf, 1, COPY_BUF, src)) > 0)
        fwrite(buf, 1, n, dest);
    free(buf);
    fclose(src);
    fclose(dest);
    unlink(tmp_path);
}

static void classify_region(VMA *v) {
    const char *p = v->pathname;

    /* HarmonyOS / Linux 匿名区域命名模式 */
    if (strstr(p, "[anon:"))          strcpy(v->region_type, "anon");
    else if (strstr(p, "[heap]"))     strcpy(v->region_type, "heap");
    else if (strstr(p, "[stack"))     strcpy(v->region_type, "stack");
    else if (strstr(p, "[vdso]"))     strcpy(v->region_type, "vdso");
    else if (strstr(p, "[vvar]"))     strcpy(v->region_type, "vdso");
    else if (strlen(p) == 0)          strcpy(v->region_type, "anon");
    else if (strstr(p, ".so"))        strcpy(v->region_type, "shared_lib");
    else if (strstr(p, "/"))          strcpy(v->region_type, "file");
    else                              strcpy(v->region_type, "other");
}

static int parse_maps(int pid, VMA *vmas, int *nvma) {
    char path[256], line[LINE_BUF];
    snprintf(path, sizeof(path), "/proc/%d/maps", pid);
    FILE *fp = fopen(path, "r");
    if (!fp) return -1;

    int n = 0;
    while (fgets(line, sizeof(line), fp) && n < MAX_VMAS) {
        VMA v;
        memset(&v, 0, sizeof(v));
        char pathname[4096] = {0};

        int got = sscanf(line, "%lx-%lx %15s %lx %63s %lu %4095[^\n]",
                         &v.start, &v.end, v.perms, &v.offset, v.dev, &v.inode, pathname);
        if (got < 6 || v.end <= v.start) continue;
        if (got >= 7) {
            while (pathname[0] == ' ') memmove(pathname, pathname + 1, strlen(pathname));
            strncpy(v.pathname, pathname, sizeof(v.pathname)-1);
        } else {
            v.pathname[0] = 0;
        }
        v.rss_kb = v.pss_kb = v.referenced_kb = v.anonymous_kb = v.swap_kb = 0;
        v.shared_clean_kb = v.shared_dirty_kb = v.private_clean_kb = v.private_dirty_kb = 0;
        v.locked_kb = 0;
        classify_region(&v);
        vmas[n++] = v;
    }
    fclose(fp);
    *nvma = n;
    return 0;
}

static int find_vma(VMA *vmas, int nvma, unsigned long start, unsigned long end) {
    for (int i=0; i<nvma; ++i)
        if (vmas[i].start == start && vmas[i].end == end) return i;
    return -1;
}

static void parse_smaps(int pid, VMA *vmas, int nvma) {
    char path[256], line[LINE_BUF];
    snprintf(path, sizeof(path), "/proc/%d/smaps", pid);
    FILE *fp = fopen(path, "r");
    if (!fp) return;

    int cur = -1;
    while (fgets(line, sizeof(line), fp)) {
        unsigned long s=0,e=0,off=0,inode=0;
        char perms[16]={0}, dev[64]={0}, pn[4096]={0};
        int got = sscanf(line, "%lx-%lx %15s %lx %63s %lu %4095[^\n]",
                         &s, &e, perms, &off, dev, &inode, pn);
        if (got >= 6 && e > s) {
            cur = find_vma(vmas, nvma, s, e);
            continue;
        }
        if (cur < 0) continue;

        long val = 0;
        if (sscanf(line, "Rss: %ld kB", &val) == 1) vmas[cur].rss_kb = val;
        else if (sscanf(line, "Pss: %ld kB", &val) == 1) vmas[cur].pss_kb = val;
        else if (sscanf(line, "Referenced: %ld kB", &val) == 1) vmas[cur].referenced_kb = val;
        else if (sscanf(line, "Anonymous: %ld kB", &val) == 1) vmas[cur].anonymous_kb = val;
        else if (sscanf(line, "Swap: %ld kB", &val) == 1) vmas[cur].swap_kb = val;
        else if (sscanf(line, "Shared_Clean: %ld kB", &val) == 1) vmas[cur].shared_clean_kb = val;
        else if (sscanf(line, "Shared_Dirty: %ld kB", &val) == 1) vmas[cur].shared_dirty_kb = val;
        else if (sscanf(line, "Private_Clean: %ld kB", &val) == 1) vmas[cur].private_clean_kb = val;
        else if (sscanf(line, "Private_Dirty: %ld kB", &val) == 1) vmas[cur].private_dirty_kb = val;
        else if (sscanf(line, "Locked: %ld kB", &val) == 1) vmas[cur].locked_kb = val;
        else if (strncmp(line, "VmFlags:", 8) == 0) {
            char *p = line + 8;
            while (*p == ' ' || *p == '\t') p++;
            size_t len = strlen(p);
            while (len && (p[len-1]=='\n' || p[len-1]=='\r')) p[--len]=0;
            strncpy(vmas[cur].vm_flags, p, sizeof(vmas[cur].vm_flags)-1);
        }
    }
    fclose(fp);
}

static void append_headers(const char *outdir) {
    char p[1024];
    snprintf(p, sizeof(p), "%s/app_list.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"app_id,app_name,process_name,app_type,note\n"); fclose(f);}
    }

    snprintf(p, sizeof(p), "%s/operation_list.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"operation_id,app_id,app_name,process_name,pid,operation_name,operation_description,foreground_state,manual_or_auto,timestamp_ms,sample_id,snapshot_index,note\n"); fclose(f);}
    }

    snprintf(p, sizeof(p), "%s/snapshot_index.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"sample_id,operation_id,app_id,app_name,process_name,pid,timestamp_ms,snapshot_index,foreground_state,collect_status,note\n"); fclose(f);}
    }

    snprintf(p, sizeof(p), "%s/vma_memory_snapshot.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"sample_id,operation_id,app_id,app_name,process_name,pid,timestamp_ms,snapshot_index,vma_id,vma_start,vma_end,vma_size_kb,perms,offset,dev,inode,pathname,region_type,rss_kb,pss_kb,referenced_kb,anonymous_kb,swap_kb,shared_clean_kb,shared_dirty_kb,private_clean_kb,private_dirty_kb,locked_kb,vm_flags,note\n"); fclose(f);}
    }

    snprintf(p, sizeof(p), "%s/pagemap_snapshot.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"sample_id,operation_id,app_id,app_name,process_name,pid,timestamp_ms,snapshot_index,vma_id,vma_start,vma_end,page_count,present_pages,not_present_pages,swapped_pages,file_or_shared_pages,exclusive_pages,soft_dirty_pages,present_ratio,swapped_ratio,scan_status,note\n"); fclose(f);}
    }

    snprintf(p, sizeof(p), "%s/future_need_label.csv", outdir);
    if (!file_exists(p)) {
        FILE *f=fopen(p,"w");
        if(f){fprintf(f,"label_id,sample_id,operation_id,next_operation_id,app_id,app_name,process_name,pid,vma_id,region_type,revisit_in_1s,revisit_in_3s,revisit_in_5s,should_keep,reason,note\n"); fclose(f);}
    }
}

static void append_snapshot_index(const char *outdir, const char *sample_id, const char *operation_id,
    const char *app_id, const char *app_name, const char *process_name, int pid,
    long long ts, const char *snapshot_index, const char *fg, const char *status, const char *note) {
    char p[1024];
    snprintf(p, sizeof(p), "%s/snapshot_index.csv", outdir);
    FILE *f = fopen(p, "a");
    if (!f) return;
    fprintf(f, "%s,%s,%s,", sample_id, operation_id, app_id);
    csv_escape(f, app_name); fprintf(f, ",");
    csv_escape(f, process_name); fprintf(f, ",%d,%lld,%s,%s,%s,", pid, ts, snapshot_index, fg, status);
    csv_escape(f, note);
    fprintf(f, "\n");
    fclose(f);
}

static void write_vma_csv(const char *outdir, VMA *vmas, int nvma, const char *sample_id, const char *operation_id,
    const char *app_id, const char *app_name, const char *process_name, int pid,
    long long ts, const char *snapshot_index) {
    char dest[1024], tmp[1024];
    snprintf(dest, sizeof(dest), "%s/vma_memory_snapshot.csv", outdir);
    snprintf(tmp, sizeof(tmp), "%s/vma_memory_snapshot.csv.tmp.%d", outdir, pid);
    FILE *f = fopen(tmp, "w");
    if (!f) return;

    for (int i=0; i<nvma; ++i) {
        unsigned long size_kb = (vmas[i].end - vmas[i].start) / 1024UL;
        fprintf(f, "%s,%s,%s,", sample_id, operation_id, app_id);
        csv_escape(f, app_name); fprintf(f, ",");
        csv_escape(f, process_name);
        fprintf(f, ",%d,%lld,%s,vma_%06d,0x%lx,0x%lx,%lu,%s,0x%lx,%s,%lu,",
                pid, ts, snapshot_index, i+1, vmas[i].start, vmas[i].end, size_kb,
                vmas[i].perms, vmas[i].offset, vmas[i].dev, vmas[i].inode);
        csv_escape(f, vmas[i].pathname); fprintf(f, ",");
        csv_escape(f, vmas[i].region_type);
        fprintf(f, ",%ld,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%ld,%ld,",
                vmas[i].rss_kb, vmas[i].pss_kb,
                vmas[i].referenced_kb, vmas[i].anonymous_kb, vmas[i].swap_kb,
                vmas[i].shared_clean_kb, vmas[i].shared_dirty_kb,
                vmas[i].private_clean_kb, vmas[i].private_dirty_kb,
                vmas[i].locked_kb);
        csv_escape(f, vmas[i].vm_flags);
        fprintf(f, ",\n");
    }
    fclose(f);
    append_temp_to_file(tmp, dest);
}

#define PM_PRESENT(e)    (((e) >> 63) & 1ULL)
#define PM_SWAPPED(e)    (((e) >> 62) & 1ULL)
#define PM_FILESHARED(e) (((e) >> 61) & 1ULL)
#define PM_EXCLUSIVE(e)  (((e) >> 56) & 1ULL)
#define PM_SOFTDIRTY(e)  (((e) >> 55) & 1ULL)

static void write_pagemap_csv(const char *outdir, VMA *vmas, int nvma, const char *sample_id, const char *operation_id,
    const char *app_id, const char *app_name, const char *process_name, int pid,
    long long ts, const char *snapshot_index) {
    char pm_path[256], dest[1024], tmp[1024];
    snprintf(pm_path, sizeof(pm_path), "/proc/%d/pagemap", pid);
    int fd = open(pm_path, O_RDONLY);

    snprintf(dest, sizeof(dest), "%s/pagemap_snapshot.csv", outdir);
    snprintf(tmp, sizeof(tmp), "%s/pagemap_snapshot.csv.tmp.%d", outdir, pid);
    FILE *f = fopen(tmp, "w");
    if (!f) return;

    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) page_size = 4096;

    for (int i=0; i<nvma; ++i) {
        unsigned long pages = (vmas[i].end - vmas[i].start) / (unsigned long)page_size;
        unsigned long present=0, swapped=0, not_present=0, fileshared=0, exclusive=0, softdirty=0;
        const char *status = "success";

        if (fd < 0) {
            status = "open_pagemap_failed";
            pages = present = swapped = not_present = fileshared = exclusive = softdirty = 0;
        } else {
            for (unsigned long j=0; j<pages; ++j) {
                unsigned long vaddr = vmas[i].start + j * (unsigned long)page_size;
                off_t off = (off_t)(vaddr / (unsigned long)page_size) * 8;
                uint64_t entry = 0;
                ssize_t r = pread(fd, &entry, sizeof(entry), off);
                if (r != sizeof(entry)) {
                    status = "partial_scan";
                    continue;
                }
                if (PM_PRESENT(entry)) present++;
                else if (PM_SWAPPED(entry)) swapped++;
                else not_present++;

                if (PM_FILESHARED(entry)) fileshared++;
                if (PM_EXCLUSIVE(entry)) exclusive++;
                if (PM_SOFTDIRTY(entry)) softdirty++;
            }
        }

        double present_ratio = pages ? (double)present / (double)pages : 0.0;
        double swapped_ratio = pages ? (double)swapped / (double)pages : 0.0;

        fprintf(f, "%s,%s,%s,", sample_id, operation_id, app_id);
        csv_escape(f, app_name); fprintf(f, ",");
        csv_escape(f, process_name);
        fprintf(f, ",%d,%lld,%s,vma_%06d,0x%lx,0x%lx,%lu,%lu,%lu,%lu,%lu,%lu,%lu,%.6f,%.6f,%s,\n",
                pid, ts, snapshot_index, i+1, vmas[i].start, vmas[i].end,
                pages, present, not_present, swapped, fileshared, exclusive, softdirty,
                present_ratio, swapped_ratio, status);
    }

    if (fd >= 0) close(fd);
    fclose(f);
    append_temp_to_file(tmp, dest);
}

int main(int argc, char **argv) {
    if (argc < 10) {
        fprintf(stderr, "usage: %s <pid> <out_dir> <sample_id> <operation_id> <app_id> <app_name> <process_name> <snapshot_index> <foreground_state>\n", argv[0]);
        return 1;
    }

    int pid = atoi(argv[1]);
    const char *outdir = argv[2];
    const char *sample_id = argv[3];
    const char *operation_id = argv[4];
    const char *app_id = argv[5];
    const char *app_name = argv[6];
    const char *process_name = argv[7];
    const char *snapshot_index = argv[8];
    const char *fg = argv[9];

    ensure_dir(outdir);
    append_headers(outdir);

    long long ts = now_ms();

    VMA *vmas = (VMA *)calloc(MAX_VMAS, sizeof(VMA));
    if (!vmas) {
        append_snapshot_index(outdir, sample_id, operation_id, app_id, app_name, process_name, pid, ts, snapshot_index, fg, "alloc_failed", "");
        return 2;
    }

    int nvma = 0;
    if (parse_maps(pid, vmas, &nvma) != 0) {
        append_snapshot_index(outdir, sample_id, operation_id, app_id, app_name, process_name, pid, ts, snapshot_index, fg, "open_maps_failed", strerror(errno));
        free(vmas);
        return 3;
    }

    parse_smaps(pid, vmas, nvma);

    append_snapshot_index(outdir, sample_id, operation_id, app_id, app_name, process_name, pid, ts, snapshot_index, fg, "success", "");
    write_vma_csv(outdir, vmas, nvma, sample_id, operation_id, app_id, app_name, process_name, pid, ts, snapshot_index);
    write_pagemap_csv(outdir, vmas, nvma, sample_id, operation_id, app_id, app_name, process_name, pid, ts, snapshot_index);

    free(vmas);
    return 0;
}
