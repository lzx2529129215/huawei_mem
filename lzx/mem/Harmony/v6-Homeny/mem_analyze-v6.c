#define _GNU_SOURCE

#include <ctype.h>
#include <errno.h>
#include <inttypes.h>
#include <limits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>

typedef enum {
    SEG_ARK_TS_HEAP = 0,
    SEG_NATIVE_HEAP,
    SEG_ANON_PAGE_OTHER,
    SEG_FILE_PAGE_OTHER,
    SEG_STACK,
    SEG_SO,
    SEG_HAP,
    SEG_TTF,
    SEG_DEV,
    SEG_GL,
    SEG_GRAPH,
    SEG_GUARD,
    SEG_UNKNOWN,
    SEG_COUNT
} SegmentKind;

typedef enum {
    MAP_FILE = 0,
    MAP_SHARED_LIBRARY,
    MAP_HAP_FILE,
    MAP_FONT_FILE,
    MAP_DOCUMENT_FILE,
    MAP_ANON_HEAP,
    MAP_ANON_STACK,
    MAP_NAMED_ANON,
    MAP_ANON_OTHER,
    MAP_GRAPHICS_DEVICE,
    MAP_OTHER_DEVICE,
    MAP_GUARD,
    MAP_UNKNOWN
} MappingType;

typedef struct {
    uint64_t start;
    uint64_t end;
    uint64_t offset;
    unsigned long long inode;
    char perms[8];
    char dev[32];
    char path[PATH_MAX];
    SegmentKind segment;
    MappingType mapping_type;
    long size_kb;
    long rss_kb;
    long pss_kb;
    long referenced_kb;
    long swap_kb;
} Vma;

typedef struct {
    Vma *items;
    size_t count;
    size_t cap;
} VmaList;

typedef struct {
    size_t vma_count;
    uint64_t addr_min;
    uint64_t addr_max;
    long size_kb;
    long rss_kb;
    long pss_kb;
    long referenced_kb;
    long swap_kb;
} SegmentSummary;

typedef struct {
    const Vma *v;
} VmaRefRow;

static unsigned long long kb_to_pages(long kb, long page_size);

static const char *segment_name(SegmentKind s)
{
    switch (s) {
    case SEG_ARK_TS_HEAP: return "ark ts heap";
    case SEG_NATIVE_HEAP: return "native heap";
    case SEG_ANON_PAGE_OTHER: return "AnonPage other";
    case SEG_FILE_PAGE_OTHER: return "FilePage other";
    case SEG_STACK: return "stack";
    case SEG_SO: return ".so";
    case SEG_HAP: return ".hap";
    case SEG_TTF: return ".ttf";
    case SEG_DEV: return "dev";
    case SEG_GL: return "GL";
    case SEG_GRAPH: return "Graph";
    case SEG_GUARD: return "guard";
    default: return "unknown";
    }
}

static const char *mapping_type_name(MappingType type)
{
    switch (type) {
    case MAP_FILE: return "FILE";
    case MAP_SHARED_LIBRARY: return "SHARED_LIBRARY";
    case MAP_HAP_FILE: return "HAP_FILE";
    case MAP_FONT_FILE: return "FONT_FILE";
    case MAP_DOCUMENT_FILE: return "DOCUMENT_FILE";
    case MAP_ANON_HEAP: return "ANON_HEAP";
    case MAP_ANON_STACK: return "ANON_STACK";
    case MAP_NAMED_ANON: return "NAMED_ANON";
    case MAP_ANON_OTHER: return "ANON_OTHER";
    case MAP_GRAPHICS_DEVICE: return "GRAPHICS_DEVICE";
    case MAP_OTHER_DEVICE: return "OTHER_DEVICE";
    case MAP_GUARD: return "GUARD";
    default: return "UNKNOWN";
    }
}

static void usage(const char *argv0)
{
    fprintf(stderr,
            "用法:\n"
            "  sudo %s --clear-refs <pid>\n"
            "  sudo %s --clear-refs --app firefox\n"
            "  sudo %s <pid> -o referenced.md --jsonl-output referenced.jsonl\n\n"
            "  sudo %s --app firefox -o referenced.md --jsonl-output referenced.jsonl\n\n"
            "可选:\n"
            "  --with-vma              额外输出 `## Referenced VMA 定位` 明细表\n"
            "  --jsonl-output <path>    输出全量 VMA JSONL（包括 Referenced=0）\n\n"
            "v6 只做 Referenced 工作流：clear_refs 后执行用户操作，再读取 smaps，输出 VMA/segment 表。\n",
            argv0, argv0, argv0, argv0);
}

static char *trim_left(char *s)
{
    while (*s == ' ' || *s == '\t') s++;
    return s;
}

static void trim_right(char *s)
{
    size_t n = strlen(s);
    while (n > 0 && (s[n - 1] == '\n' || s[n - 1] == '\r' ||
                     s[n - 1] == ' ' || s[n - 1] == '\t')) {
        s[--n] = '\0';
    }
}

static bool starts_with(const char *s, const char *prefix)
{
    return strncmp(s, prefix, strlen(prefix)) == 0;
}

static void clean_deleted_suffix(const char *in, char *out, size_t len)
{
    const char *suffix = " (deleted)";
    size_t n;
    snprintf(out, len, "%s", in);
    n = strlen(out);
    if (n >= strlen(suffix) && strcmp(out + n - strlen(suffix), suffix) == 0) {
        out[n - strlen(suffix)] = '\0';
    }
}

static bool ends_with(const char *s, const char *suffix)
{
    size_t s_len;
    size_t suffix_len;

    if (s == NULL || suffix == NULL) return false;
    s_len = strlen(s);
    suffix_len = strlen(suffix);
    if (suffix_len > s_len) return false;
    return strcmp(s + s_len - suffix_len, suffix) == 0;
}

static bool contains_ci(const char *haystack, const char *needle)
{
    size_t needle_len;

    if (haystack == NULL || needle == NULL) return false;
    needle_len = strlen(needle);
    if (needle_len == 0) return true;

    for (const char *p = haystack; *p != '\0'; p++) {
        size_t i;
        for (i = 0; i < needle_len; i++) {
            if (p[i] == '\0') return false;
            if (tolower((unsigned char)p[i]) != tolower((unsigned char)needle[i])) break;
        }
        if (i == needle_len) return true;
    }
    return false;
}

static bool has_file_suffix(const char *path, const char *suffix)
{
    char clean[PATH_MAX];
    clean_deleted_suffix(path, clean, sizeof(clean));
    return ends_with(clean, suffix);
}

static bool is_dev_path(const char *path)
{
    return starts_with(path, "/dev/") || starts_with(path, "anon_inode:");
}

static bool is_guard_path(const char *path, const char *perms)
{
    return contains_ci(path, "guard") ||
           strcmp(path, "[anon:thread signal stack guard page]") == 0 ||
           (perms != NULL && perms[0] == '-' && perms[1] == '-' && perms[2] == '-');
}

static bool is_graph_path(const char *path)
{
    return contains_ci(path, "graph") ||
           contains_ci(path, "graphic") ||
           contains_ci(path, "gralloc") ||
           contains_ci(path, "surface") ||
           contains_ci(path, "framebuffer") ||
           contains_ci(path, "frame_buffer") ||
           contains_ci(path, "bufferqueue") ||
           contains_ci(path, "sharedbuffer");
}

static bool is_gl_path(const char *path)
{
    return contains_ci(path, "gl") ||
           contains_ci(path, "egl") ||
           contains_ci(path, "gles") ||
           contains_ci(path, "gpu") ||
           contains_ci(path, "mali") ||
           contains_ci(path, "vulkan") ||
           contains_ci(path, "render");
}

static bool is_ark_ts_heap_path(const char *path)
{
    return contains_ci(path, "ark ts heap") ||
           contains_ci(path, "arkts heap") ||
           contains_ci(path, "ark heap") ||
           contains_ci(path, "ets heap") ||
           contains_ci(path, "js heap") ||
           (contains_ci(path, "ark") && contains_ci(path, "heap"));
}

static bool is_native_heap_path(const char *path)
{
    if (strcmp(path, "[heap]") == 0) return true;
    return contains_ci(path, "native heap") ||
           contains_ci(path, "malloc") ||
           contains_ci(path, "jemalloc") ||
           contains_ci(path, "scudo") ||
           contains_ci(path, "libc_malloc") ||
           contains_ci(path, "heap");
}

static bool mkdir_p(const char *path)
{
    char tmp[PATH_MAX];
    size_t len;

    if (path[0] == '\0') return true;
    if (snprintf(tmp, sizeof(tmp), "%s", path) >= (int)sizeof(tmp)) {
        errno = ENAMETOOLONG;
        return false;
    }
    len = strlen(tmp);
    while (len > 1 && tmp[len - 1] == '/') tmp[--len] = '\0';
    for (char *p = tmp + 1; *p != '\0'; p++) {
        if (*p != '/') continue;
        *p = '\0';
        if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return false;
        *p = '/';
    }
    if (mkdir(tmp, 0755) != 0 && errno != EEXIST) return false;
    return true;
}

static bool ensure_parent_dir(const char *path)
{
    char parent[PATH_MAX];
    const char *slash = strrchr(path, '/');
    size_t len;

    if (slash == NULL) return true;
    len = (size_t)(slash - path);
    if (len == 0) len = 1;
    if (len >= sizeof(parent)) {
        errno = ENAMETOOLONG;
        return false;
    }
    memcpy(parent, path, len);
    parent[len] = '\0';
    return mkdir_p(parent);
}

static bool vma_list_push(VmaList *list, const Vma *vma)
{
    if (list->count == list->cap) {
        size_t new_cap = list->cap == 0 ? 64 : list->cap * 2;
        Vma *items = realloc(list->items, new_cap * sizeof(*items));
        if (items == NULL) return false;
        list->items = items;
        list->cap = new_cap;
    }
    list->items[list->count++] = *vma;
    return true;
}

static void vma_list_free(VmaList *list)
{
    free(list->items);
    list->items = NULL;
    list->count = 0;
    list->cap = 0;
}

static bool parse_maps_header(const char *line, Vma *vma)
{
    unsigned long long start = 0, end = 0, offset = 0, inode = 0;
    char perms[8] = {0};
    char dev[32] = {0};
    int path_pos = 0;
    int matched;

    memset(vma, 0, sizeof(*vma));
    vma->segment = SEG_UNKNOWN;
    vma->mapping_type = MAP_UNKNOWN;
    vma->size_kb = -1;
    vma->rss_kb = -1;
    vma->pss_kb = -1;
    vma->referenced_kb = -1;
    vma->swap_kb = -1;

    matched = sscanf(line, "%llx-%llx %7s %llx %31s %llu %n",
                     &start, &end, perms, &offset, dev, &inode, &path_pos);
    if (matched < 6) return false;

    vma->start = start;
    vma->end = end;
    vma->offset = offset;
    vma->inode = inode;
    snprintf(vma->perms, sizeof(vma->perms), "%s", perms);
    snprintf(vma->dev, sizeof(vma->dev), "%s", dev);
    if (path_pos > 0 && line[path_pos] != '\0') {
        char tmp[PATH_MAX];
        snprintf(tmp, sizeof(tmp), "%s", line + path_pos);
        trim_right(tmp);
        snprintf(vma->path, sizeof(vma->path), "%s", trim_left(tmp));
    }
    return true;
}

static bool is_header_line(const char *line)
{
    unsigned long long a, b, off, inode;
    char perms[8], dev[32];
    return sscanf(line, "%llx-%llx %7s %llx %31s %llu",
                  &a, &b, perms, &off, dev, &inode) == 6;
}

static long parse_kb_value(const char *value)
{
    long kb = -1;
    if (sscanf(value, "%ld", &kb) == 1) return kb;
    return -1;
}

static void apply_smap_value(Vma *vma, const char *key, const char *value)
{
    long kb = parse_kb_value(value);
    if (strcmp(key, "Size") == 0) vma->size_kb = kb;
    else if (strcmp(key, "Rss") == 0) vma->rss_kb = kb;
    else if (strcmp(key, "Pss") == 0) vma->pss_kb = kb;
    else if (strcmp(key, "Referenced") == 0) vma->referenced_kb = kb;
    else if (strcmp(key, "Swap") == 0) vma->swap_kb = kb;
}

static bool parse_smaps(pid_t pid, VmaList *list, char *err, size_t err_len)
{
    char path[64];
    FILE *fp;
    char *line = NULL;
    size_t line_cap = 0;
    Vma current;
    bool have_current = false;
    bool ok = true;

    snprintf(path, sizeof(path), "/proc/%ld/smaps", (long)pid);
    fp = fopen(path, "r");
    if (fp == NULL) {
        snprintf(err, err_len, "cannot read %s: %s", path, strerror(errno));
        return false;
    }

    while (getline(&line, &line_cap, fp) != -1) {
        if (is_header_line(line)) {
            if (have_current && !vma_list_push(list, &current)) {
                snprintf(err, err_len, "out of memory while saving VMA information");
                ok = false;
                break;
            }
            if (!parse_maps_header(line, &current)) {
                snprintf(err, err_len, "cannot parse smaps header: %s", line);
                ok = false;
                break;
            }
            have_current = true;
            continue;
        }

        if (have_current) {
            char *colon = strchr(line, ':');
            if (colon != NULL) {
                *colon = '\0';
                char *key = trim_left(line);
                char *value = trim_left(colon + 1);
                trim_right(key);
                trim_right(value);
                apply_smap_value(&current, key, value);
            }
        }
    }

    if (ok && have_current && !vma_list_push(list, &current)) {
        snprintf(err, err_len, "out of memory while saving VMA information");
        ok = false;
    }

    free(line);
    fclose(fp);
    return ok;
}

static void read_comm(pid_t pid, char *buf, size_t len)
{
    char path[64];
    FILE *fp;
    snprintf(path, sizeof(path), "/proc/%ld/comm", (long)pid);
    fp = fopen(path, "r");
    if (fp == NULL || fgets(buf, (int)len, fp) == NULL) {
        snprintf(buf, len, "unknown");
    }
    trim_right(buf);
    if (fp != NULL) fclose(fp);
}

static void read_cmdline(pid_t pid, char *buf, size_t len)
{
    char path[64];
    FILE *fp;
    size_t n;

    if (len == 0) return;
    buf[0] = '\0';
    snprintf(path, sizeof(path), "/proc/%ld/cmdline", (long)pid);
    fp = fopen(path, "r");
    if (fp == NULL) return;
    n = fread(buf, 1, len - 1, fp);
    fclose(fp);
    buf[n] = '\0';
    for (size_t i = 0; i < n; i++) {
        if (buf[i] == '\0') buf[i] = ' ';
    }
    trim_right(buf);
}

static void read_exe_path(pid_t pid, char *buf, size_t len)
{
    char path[64];
    ssize_t n;
    snprintf(path, sizeof(path), "/proc/%ld/exe", (long)pid);
    n = readlink(path, buf, len - 1);
    if (n < 0) {
        buf[0] = '\0';
        return;
    }
    buf[n] = '\0';
}

static bool string_contains(const char *haystack, const char *needle)
{
    return haystack != NULL && needle != NULL && strstr(haystack, needle) != NULL;
}

static int discover_app_pids(const char *keyword, pid_t *pids, int max_pids)
{
    DIR *dir = opendir("/proc");
    struct dirent *ent;
    int count = 0;
    pid_t self_pid = getpid();
    pid_t parent_pid = getppid();

    if (dir == NULL) return 0;
    while ((ent = readdir(dir)) != NULL) {
        char *end = NULL;
        long pid_long = strtol(ent->d_name, &end, 10);
        if (end == ent->d_name || *end != '\0' || pid_long <= 0 || pid_long > INT_MAX) {
            continue;
        }

        pid_t pid = (pid_t)pid_long;
        char comm[256];
        char cmdline[1024];
        if (pid == self_pid || pid == parent_pid) {
            continue;
        }
        read_comm(pid, comm, sizeof(comm));
        read_cmdline(pid, cmdline, sizeof(cmdline));
        if (string_contains(comm, keyword) || string_contains(cmdline, keyword)) {
            bool exists = false;
            for (int i = 0; i < count; i++) {
                if (pids[i] == pid) {
                    exists = true;
                    break;
                }
            }
            if (!exists && count < max_pids) {
                pids[count++] = pid;
            }
        }
    }
    closedir(dir);
    return count;
}

static void classify_segments(VmaList *list, const char *exe_path)
{
    (void)exe_path;

    for (size_t i = 0; i < list->count; i++) {
        Vma *v = &list->items[i];
        bool is_anon = (v->inode == 0 && v->path[0] == '\0') || starts_with(v->path, "[anon:");

        if (is_guard_path(v->path, v->perms)) {
            v->segment = SEG_GUARD;
        } else if (starts_with(v->path, "[stack")) {
            v->segment = SEG_STACK;
        } else if (is_ark_ts_heap_path(v->path)) {
            v->segment = SEG_ARK_TS_HEAP;
        } else if (is_native_heap_path(v->path)) {
            v->segment = SEG_NATIVE_HEAP;
        } else if (is_dev_path(v->path)) {
            v->segment = SEG_DEV;
        } else if (is_gl_path(v->path)) {
            v->segment = SEG_GL;
        } else if (is_graph_path(v->path)) {
            v->segment = SEG_GRAPH;
        } else if (has_file_suffix(v->path, ".so")) {
            v->segment = SEG_SO;
        } else if (has_file_suffix(v->path, ".hap")) {
            v->segment = SEG_HAP;
        } else if (has_file_suffix(v->path, ".ttf") || has_file_suffix(v->path, ".otf")) {
            v->segment = SEG_TTF;
        } else if (is_anon) {
            v->segment = SEG_ANON_PAGE_OTHER;
        } else if (v->path[0] != '\0') {
            v->segment = SEG_FILE_PAGE_OTHER;
        } else {
            v->segment = SEG_UNKNOWN;
        }
    }
}

static bool is_document_path(const char *path)
{
    return has_file_suffix(path, ".doc") || has_file_suffix(path, ".docx") ||
           has_file_suffix(path, ".wps") || has_file_suffix(path, ".pdf") ||
           has_file_suffix(path, ".txt") || has_file_suffix(path, ".rtf");
}

static MappingType classify_mapping_type(const Vma *v)
{
    bool inode_file = v->inode != 0 && v->path[0] != '\0' && !is_dev_path(v->path);

    if (is_guard_path(v->path, v->perms)) return MAP_GUARD;
    if (starts_with(v->path, "[stack")) return MAP_ANON_STACK;
    if (strcmp(v->path, "[heap]") == 0 || is_native_heap_path(v->path) ||
        is_ark_ts_heap_path(v->path)) return MAP_ANON_HEAP;
    if (is_dev_path(v->path)) {
        return (is_graph_path(v->path) || is_gl_path(v->path)) ?
               MAP_GRAPHICS_DEVICE : MAP_OTHER_DEVICE;
    }
    if (inode_file && (has_file_suffix(v->path, ".so") || contains_ci(v->path, ".so."))) {
        return MAP_SHARED_LIBRARY;
    }
    if (inode_file && has_file_suffix(v->path, ".hap")) return MAP_HAP_FILE;
    if (inode_file && (has_file_suffix(v->path, ".ttf") || has_file_suffix(v->path, ".otf"))) {
        return MAP_FONT_FILE;
    }
    if (inode_file && is_document_path(v->path)) return MAP_DOCUMENT_FILE;
    if (inode_file) return MAP_FILE;
    if (starts_with(v->path, "[anon:") || starts_with(v->path, "/anon_hugepage") ||
        starts_with(v->path, "anon_inode:")) return MAP_NAMED_ANON;
    if (v->inode == 0 && v->path[0] == '\0') return MAP_ANON_OTHER;
    return MAP_UNKNOWN;
}

static void classify_mapping_types(VmaList *list)
{
    for (size_t i = 0; i < list->count; i++) {
        list->items[i].mapping_type = classify_mapping_type(&list->items[i]);
    }
}

static bool clear_referenced_bits(pid_t pid, char *err, size_t err_len)
{
    char path[64];
    int fd;
    ssize_t n;

    snprintf(path, sizeof(path), "/proc/%ld/clear_refs", (long)pid);
    fd = open(path, O_WRONLY);
    if (fd < 0) {
        snprintf(err, err_len, "cannot open %s: %s", path, strerror(errno));
        return false;
    }
    n = write(fd, "1\n", 2);
    if (n != 2) {
        snprintf(err, err_len, "cannot write %s: %s", path, strerror(errno));
        close(fd);
        return false;
    }
    close(fd);
    return true;
}

static void print_md_text_cell(FILE *out, const char *s)
{
    for (const char *p = s; *p != '\0'; p++) {
        if (*p == '|') fputs("\\|", out);
        else if (*p == '\n' || *p == '\r') fputc(' ', out);
        else fputc(*p, out);
    }
}

static void json_write_string(FILE *out, const char *s)
{
    const unsigned char *p = (const unsigned char *)(s != NULL ? s : "");
    fputc('"', out);
    while (*p != '\0') {
        switch (*p) {
        case '"': fputs("\\\"", out); break;
        case '\\': fputs("\\\\", out); break;
        case '\b': fputs("\\b", out); break;
        case '\f': fputs("\\f", out); break;
        case '\n': fputs("\\n", out); break;
        case '\r': fputs("\\r", out); break;
        case '\t': fputs("\\t", out); break;
        default:
            if (*p < 0x20U) fprintf(out, "\\u%04x", (unsigned int)*p);
            else fputc((int)*p, out);
            break;
        }
        p++;
    }
    fputc('"', out);
}

static bool path_has_deleted_suffix(const char *path)
{
    return ends_with(path, " (deleted)");
}

static bool parse_device_numbers(const char *device, unsigned int *major_num, unsigned int *minor_num)
{
    unsigned int major_value = 0;
    unsigned int minor_value = 0;
    if (sscanf(device, "%x:%x", &major_value, &minor_value) != 2) return false;
    *major_num = major_value;
    *minor_num = minor_value;
    return true;
}

static void format_wall_time(char *buf, size_t len, const struct timespec *ts)
{
    struct tm tm_value;
    char base[32];
    if (gmtime_r(&ts->tv_sec, &tm_value) == NULL ||
        strftime(base, sizeof(base), "%Y-%m-%dT%H:%M:%S", &tm_value) == 0) {
        snprintf(buf, len, "unknown");
        return;
    }
    snprintf(buf, len, "%s.%09ldZ", base, ts->tv_nsec);
}

static void json_write_nullable_long(FILE *out, long value)
{
    if (value < 0) fputs("null", out);
    else fprintf(out, "%ld", value);
}

static void json_write_ratio(FILE *out, long numerator, long denominator)
{
    double ratio;
    if (numerator < 0 || denominator <= 0) {
        fputs("null", out);
        return;
    }
    ratio = (double)numerator / (double)denominator;
    if (ratio < 0.0) ratio = 0.0;
    if (ratio > 1.0) ratio = 1.0;
    fprintf(out, "%.12g", ratio);
}

static void print_jsonl(FILE *out, pid_t pid, const char *comm, const char *exe_path,
                        const VmaList *list, long page_size)
{
    struct timespec wall_ts;
    struct timespec mono_ts;
    char wall_time[64];
    uint64_t monotonic_ns;

    if (clock_gettime(CLOCK_REALTIME, &wall_ts) != 0) memset(&wall_ts, 0, sizeof(wall_ts));
    if (clock_gettime(CLOCK_MONOTONIC, &mono_ts) != 0) memset(&mono_ts, 0, sizeof(mono_ts));
    format_wall_time(wall_time, sizeof(wall_time), &wall_ts);
    monotonic_ns = (uint64_t)mono_ts.tv_sec * 1000000000ULL + (uint64_t)mono_ts.tv_nsec;

    for (size_t i = 0; i < list->count; i++) {
        const Vma *v = &list->items[i];
        uint64_t address_size = v->end >= v->start ? v->end - v->start : 0;
        uint64_t offset_end = UINT64_MAX - v->offset < address_size ? UINT64_MAX : v->offset + address_size;
        unsigned int dev_major = 0;
        unsigned int dev_minor = 0;
        bool device_available = parse_device_numbers(v->dev, &dev_major, &dev_minor);
        bool deleted = path_has_deleted_suffix(v->path);
        char normalized_path[PATH_MAX];
        char start_hex[32];
        char end_hex[32];

        clean_deleted_suffix(v->path, normalized_path, sizeof(normalized_path));
        snprintf(start_hex, sizeof(start_hex), "0x%" PRIx64, v->start);
        snprintf(end_hex, sizeof(end_hex), "0x%" PRIx64, v->end);

        fputs("{\"schema_version\":\"homeny.vma.v1\",\"record_type\":\"vma\",", out);
        fprintf(out, "\"pid\":%ld,\"process_name\":", (long)pid);
        json_write_string(out, comm);
        fputs(",\"exe_path\":", out);
        json_write_string(out, exe_path);
        fprintf(out, ",\"page_size_bytes\":%ld,\"start_address\":%" PRIu64
                     ",\"end_address\":%" PRIu64 ",\"start_address_hex\":",
                page_size, v->start, v->end);
        json_write_string(out, start_hex);
        fputs(",\"end_address_hex\":", out);
        json_write_string(out, end_hex);
        fprintf(out, ",\"address_size_bytes\":%" PRIu64 ",\"permissions\":", address_size);
        json_write_string(out, v->perms);
        fprintf(out, ",\"file_offset_bytes\":%" PRIu64 ",\"file_offset_end_bytes\":%" PRIu64
                     ",\"device\":", v->offset, offset_end);
        json_write_string(out, v->dev);
        fputs(",\"dev_major\":", out);
        if (device_available) fprintf(out, "%u", dev_major); else fputs("null", out);
        fputs(",\"dev_minor\":", out);
        if (device_available) fprintf(out, "%u", dev_minor); else fputs("null", out);
        fprintf(out, ",\"inode\":%llu,\"path\":", v->inode);
        json_write_string(out, v->path);
        fputs(",\"normalized_path\":", out);
        json_write_string(out, normalized_path);
        fprintf(out, ",\"path_deleted\":%s,\"segment\":", deleted ? "true" : "false");
        json_write_string(out, segment_name(v->segment));
        fputs(",\"mapping_type\":", out);
        json_write_string(out, mapping_type_name(v->mapping_type));
        fputs(",\"size_kib\":", out); json_write_nullable_long(out, v->size_kb);
        fputs(",\"rss_kib\":", out); json_write_nullable_long(out, v->rss_kb);
        fputs(",\"pss_kib\":", out); json_write_nullable_long(out, v->pss_kb);
        fputs(",\"referenced_kib\":", out); json_write_nullable_long(out, v->referenced_kb);
        fputs(",\"referenced_pages\":", out);
        if (v->referenced_kb < 0) fputs("null", out);
        else fprintf(out, "%llu", kb_to_pages(v->referenced_kb, page_size));
        fputs(",\"swap_kib\":", out); json_write_nullable_long(out, v->swap_kb);
        fputs(",\"referenced_size_ratio\":", out); json_write_ratio(out, v->referenced_kb, v->size_kb);
        fputs(",\"referenced_rss_ratio\":", out); json_write_ratio(out, v->referenced_kb, v->rss_kb);
        fputs(",\"sample_wall_time\":", out); json_write_string(out, wall_time);
        fprintf(out, ",\"sample_monotonic_ns\":%" PRIu64 "}\n", monotonic_ns);
    }
}

static int compare_vma_ref_rows(const void *a, const void *b)
{
    const VmaRefRow *ra = (const VmaRefRow *)a;
    const VmaRefRow *rb = (const VmaRefRow *)b;
    long ar = ra->v->referenced_kb >= 0 ? ra->v->referenced_kb : 0;
    long br = rb->v->referenced_kb >= 0 ? rb->v->referenced_kb : 0;
    if (ar < br) return 1;
    if (ar > br) return -1;
    if (ra->v->start < rb->v->start) return -1;
    if (ra->v->start > rb->v->start) return 1;
    return 0;
}

static void build_segment_summaries(const VmaList *list, SegmentSummary sums[SEG_COUNT])
{
    memset(sums, 0, sizeof(SegmentSummary) * SEG_COUNT);
    for (int s = 0; s < SEG_COUNT; s++) sums[s].addr_min = UINT64_MAX;

    for (size_t i = 0; i < list->count; i++) {
        const Vma *v = &list->items[i];
        SegmentKind s = v->segment;
        if (s < 0 || s >= SEG_COUNT) s = SEG_UNKNOWN;
        sums[s].vma_count++;
        if (v->start < sums[s].addr_min) sums[s].addr_min = v->start;
        if (v->end > sums[s].addr_max) sums[s].addr_max = v->end;
        if (v->size_kb >= 0) sums[s].size_kb += v->size_kb;
        if (v->rss_kb >= 0) sums[s].rss_kb += v->rss_kb;
        if (v->pss_kb >= 0) sums[s].pss_kb += v->pss_kb;
        if (v->referenced_kb >= 0) sums[s].referenced_kb += v->referenced_kb;
        if (v->swap_kb >= 0) sums[s].swap_kb += v->swap_kb;
    }
}

static unsigned long long kb_to_pages(long kb, long page_size)
{
    if (kb <= 0) return 0;
    return (unsigned long long)(((uint64_t)kb * 1024ULL + (uint64_t)page_size - 1ULL) /
                                (uint64_t)page_size);
}

static void print_kb_pages_cell(FILE *out, long kb, long page_size)
{
    fprintf(out, "%ld KiB (%llu 页)", kb, kb_to_pages(kb, page_size));
}

static void print_report(FILE *out, pid_t pid, const char *comm, const char *exe_path,
                         const VmaList *list, long page_size, bool include_vma_table)
{
    SegmentSummary sums[SEG_COUNT];
    VmaRefRow *rows = NULL;
    long total_size = 0, total_rss = 0, total_pss = 0, total_ref = 0, total_swap = 0;

    build_segment_summaries(list, sums);
    for (int s = 0; s < SEG_COUNT; s++) {
        total_size += sums[s].size_kb;
        total_rss += sums[s].rss_kb;
        total_pss += sums[s].pss_kb;
        total_ref += sums[s].referenced_kb;
        total_swap += sums[s].swap_kb;
    }

    fprintf(out, "# Referenced 操作后访问定位报告\n\n");
    fprintf(out, "| 项目 | 值 |\n| --- | --- |\n");
    fprintf(out, "| PID | `%ld` |\n", (long)pid);
    fprintf(out, "| 进程名 | `");
    print_md_text_cell(out, comm);
    fprintf(out, "` |\n");
    fprintf(out, "| 可执行文件 | `");
    print_md_text_cell(out, exe_path[0] ? exe_path : "(无法读取 /proc/<pid>/exe)");
    fprintf(out, "` |\n");
    fprintf(out, "| 页大小 | `%ld bytes` |\n", page_size);
    fprintf(out, "| VMA 数 | `%zu` |\n", list->count);
    fprintf(out, "| Size | `%ld KiB` |\n", total_size);
    fprintf(out, "| Rss | `%ld KiB` |\n", total_rss);
    fprintf(out, "| Pss | `%ld KiB` |\n", total_pss);
    fprintf(out, "| Referenced | `%ld KiB / %llu 页` |\n", total_ref, kb_to_pages(total_ref, page_size));
    fprintf(out, "| Swap | `%ld KiB` |\n\n", total_swap);

    fprintf(out, "> 使用方法：先运行 `--clear-refs`，再执行用户操作，然后立刻采样。本报告中的 `Referenced` 表示观察窗口内被访问过的驻留页规模。\n\n");

    fprintf(out, "## Referenced 段汇总\n\n");
    fprintf(out, "| 一级段 | VMA 数 | Size | Rss | Pss | Referenced | Swap | Referenced/Size | Referenced/Rss |\n");
    fprintf(out, "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n");
    for (int s = 0; s < SEG_COUNT; s++) {
        if (sums[s].vma_count == 0) continue;
        double size_pct = sums[s].size_kb > 0 ? 100.0 * (double)sums[s].referenced_kb / (double)sums[s].size_kb : 0.0;
        double rss_pct = sums[s].rss_kb > 0 ? 100.0 * (double)sums[s].referenced_kb / (double)sums[s].rss_kb : 0.0;
        fprintf(out, "| %s | %zu | ", segment_name((SegmentKind)s), sums[s].vma_count);
        print_kb_pages_cell(out, sums[s].size_kb, page_size);
        fprintf(out, " | ");
        print_kb_pages_cell(out, sums[s].rss_kb, page_size);
        fprintf(out, " | ");
        print_kb_pages_cell(out, sums[s].pss_kb, page_size);
        fprintf(out, " | ");
        print_kb_pages_cell(out, sums[s].referenced_kb, page_size);
        fprintf(out, " | ");
        print_kb_pages_cell(out, sums[s].swap_kb, page_size);
        fprintf(out, " | %.2f%% | %.2f%% |\n", size_pct, rss_pct);
    }
    fprintf(out, "\n");

    if (!include_vma_table) {
        return;
    }

    rows = calloc(list->count == 0 ? 1 : list->count, sizeof(*rows));
    if (rows == NULL) {
        fprintf(out, "## Referenced VMA 定位\n\n内存不足，无法生成 VMA 表。\n");
        return;
    }
    for (size_t i = 0; i < list->count; i++) rows[i].v = &list->items[i];
    qsort(rows, list->count, sizeof(rows[0]), compare_vma_ref_rows);

    fprintf(out, "## Referenced VMA 定位\n\n");
    fprintf(out, "| VMA | 一级段 | 权限 | Size(KiB) | Rss(KiB) | Pss(KiB) | Referenced(KiB) | Referenced页 | Referenced/Size | 路径 | File Offset | Device | Inode | Referenced/Rss | Mapping Type |\n");
    fprintf(out, "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- | ---: | ---: | --- |\n");
    for (size_t i = 0; i < list->count; i++) {
        const Vma *v = rows[i].v;
        long size = v->size_kb >= 0 ? v->size_kb : 0;
        long rss = v->rss_kb >= 0 ? v->rss_kb : 0;
        long pss = v->pss_kb >= 0 ? v->pss_kb : 0;
        long ref = v->referenced_kb >= 0 ? v->referenced_kb : 0;
        double pct = size > 0 ? 100.0 * (double)ref / (double)size : 0.0;
        double rss_pct = rss > 0 ? 100.0 * (double)ref / (double)rss : 0.0;
        fprintf(out, "| `%012" PRIx64 "-%012" PRIx64 "` | %s | `%s` | %ld | %ld | %ld | %ld | %llu | %.2f%% | `",
                v->start, v->end, segment_name(v->segment), v->perms,
                size, rss, pss, ref, kb_to_pages(ref, page_size), pct);
        print_md_text_cell(out, v->path[0] ? v->path : "(anonymous)");
        fprintf(out, "` | `0x%" PRIx64 "` | `%s` | %llu | %.2f%% | %s |\n",
                v->offset, v->dev, v->inode, rss_pct, mapping_type_name(v->mapping_type));
    }
    fprintf(out, "\n");
    free(rows);
}

static void make_pid_output_path(const char *out_path, pid_t pid, int total_count,
                                 const char *default_ext, char *buf, size_t len)
{
    const char *dot;
    if (total_count <= 1) {
        snprintf(buf, len, "%s", out_path);
        return;
    }
    dot = strrchr(out_path, '.');
    if (dot != NULL && strchr(dot, '/') == NULL) {
        size_t stem_len = (size_t)(dot - out_path);
        if (stem_len >= len) stem_len = len - 1;
        memcpy(buf, out_path, stem_len);
        buf[stem_len] = '\0';
        snprintf(buf + stem_len, len - stem_len, "_pid_%ld%s", (long)pid, dot);
    } else {
        snprintf(buf, len, "%s_pid_%ld%s", out_path, (long)pid, default_ext);
    }
}

static bool analyze_pid(pid_t pid, const char *md_path, const char *jsonl_path,
                        bool include_vma_table)
{
    VmaList list = {0};
    char err[256] = {0};
    char comm[256];
    char exe_path[PATH_MAX];
    long page_size = sysconf(_SC_PAGESIZE);
    FILE *md_out;
    FILE *jsonl_out = NULL;

    if (page_size <= 0) {
        fprintf(stderr, "sysconf(_SC_PAGESIZE) failed\n");
        return false;
    }
    read_comm(pid, comm, sizeof(comm));
    read_exe_path(pid, exe_path, sizeof(exe_path));

    if (!parse_smaps(pid, &list, err, sizeof(err))) {
        fprintf(stderr, "%s\n", err);
        return false;
    }
    classify_segments(&list, exe_path);
    classify_mapping_types(&list);

    if (!ensure_parent_dir(md_path)) {
        fprintf(stderr, "cannot create parent dir for %s: %s\n", md_path, strerror(errno));
        vma_list_free(&list);
        return false;
    }

    md_out = fopen(md_path, "w");
    if (md_out == NULL) {
        fprintf(stderr, "cannot create %s: %s\n", md_path, strerror(errno));
        vma_list_free(&list);
        return false;
    }
    print_report(md_out, pid, comm, exe_path, &list, page_size, include_vma_table);
    if (fclose(md_out) != 0) {
        fprintf(stderr, "cannot finish %s: %s\n", md_path, strerror(errno));
        vma_list_free(&list);
        return false;
    }

    if (jsonl_path != NULL) {
        if (!ensure_parent_dir(jsonl_path)) {
            fprintf(stderr, "cannot create parent dir for %s: %s\n", jsonl_path, strerror(errno));
            vma_list_free(&list);
            return false;
        }
        jsonl_out = fopen(jsonl_path, "w");
        if (jsonl_out == NULL) {
            fprintf(stderr, "cannot create %s: %s\n", jsonl_path, strerror(errno));
            vma_list_free(&list);
            return false;
        }
        print_jsonl(jsonl_out, pid, comm, exe_path, &list, page_size);
        if (fclose(jsonl_out) != 0) {
            fprintf(stderr, "cannot finish %s: %s\n", jsonl_path, strerror(errno));
            vma_list_free(&list);
            return false;
        }
    }
    vma_list_free(&list);
    return true;
}

int main(int argc, char **argv)
{
    bool clear_refs = false;
    bool include_vma_table = false;
    const char *app_keyword = NULL;
    const char *out_path = "referenced.md";
    const char *jsonl_path = NULL;
    pid_t pids[256];
    int pid_count = 0;

    if (argc < 2) {
        usage(argv[0]);
        return 1;
    }

    for (int i = 1; i < argc; i++) {
        if (strcmp(argv[i], "-h") == 0 || strcmp(argv[i], "--help") == 0) {
            usage(argv[0]);
            return 0;
        }
        if (strcmp(argv[i], "--clear-refs") == 0) {
            clear_refs = true;
            continue;
        }
        if (strcmp(argv[i], "--with-vma") == 0) {
            include_vma_table = true;
            continue;
        }
        if (strcmp(argv[i], "--app") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "--app 后面需要 app 关键字\n");
                return 1;
            }
            app_keyword = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "-o") == 0 || strcmp(argv[i], "--output") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "-o/--output 后面需要报告路径\n");
                return 1;
            }
            out_path = argv[++i];
            continue;
        }
        if (strcmp(argv[i], "--jsonl-output") == 0 || strcmp(argv[i], "--jsonl-out") == 0) {
            if (i + 1 >= argc) {
                fprintf(stderr, "--jsonl-output 后面需要报告路径\n");
                return 1;
            }
            jsonl_path = argv[++i];
            continue;
        }
        char *end = NULL;
        long pid_long = strtol(argv[i], &end, 10);
        if (end == argv[i] || *end != '\0' || pid_long <= 0 || pid_long > INT_MAX) {
            fprintf(stderr, "未知参数或非法 PID: %s\n", argv[i]);
            usage(argv[0]);
            return 1;
        }
        if (pid_count >= (int)(sizeof(pids) / sizeof(pids[0]))) {
            fprintf(stderr, "PID 数量过多，最多支持 %zu 个\n", sizeof(pids) / sizeof(pids[0]));
            return 1;
        }
        pids[pid_count++] = (pid_t)pid_long;
    }

    if (app_keyword != NULL) {
        if (pid_count != 0) {
            fprintf(stderr, "请不要混用 PID 和 --app；请分别运行。\n");
            return 1;
        }
        pid_count = discover_app_pids(app_keyword, pids, (int)(sizeof(pids) / sizeof(pids[0])));
        if (pid_count == 0) {
            fprintf(stderr, "没有找到匹配 app 关键字 `%s` 的进程。\n", app_keyword);
            return 1;
        }
        fprintf(stderr, "app `%s` 匹配到 %d 个进程。\n", app_keyword, pid_count);
    }

    if (clear_refs) {
        int ok_count = 0;
        char err[256] = {0};
        if (pid_count == 0) {
            fprintf(stderr, "请指定 PID 或 --app\n");
            usage(argv[0]);
            return 1;
        }
        for (int i = 0; i < pid_count; i++) {
            err[0] = '\0';
            if (clear_referenced_bits(pids[i], err, sizeof(err))) {
                printf("PID %ld referenced 标记已清空\n", (long)pids[i]);
                ok_count++;
            } else {
                fprintf(stderr, "PID %ld 清空 referenced 失败: %s\n", (long)pids[i], err);
            }
        }
        return ok_count == pid_count ? 0 : 2;
    }

    if (pid_count == 0) {
        fprintf(stderr, "请指定 PID 或 --app\n");
        usage(argv[0]);
        return 1;
    }

    int ok_count = 0;
    for (int i = 0; i < pid_count; i++) {
        char one_md[PATH_MAX];
        char one_jsonl[PATH_MAX];
        const char *one_jsonl_ptr = NULL;
        make_pid_output_path(out_path, pids[i], pid_count, ".md", one_md, sizeof(one_md));
        if (jsonl_path != NULL) {
            make_pid_output_path(jsonl_path, pids[i], pid_count, ".jsonl",
                                 one_jsonl, sizeof(one_jsonl));
            one_jsonl_ptr = one_jsonl;
        }
        if (analyze_pid(pids[i], one_md, one_jsonl_ptr, include_vma_table)) {
            printf("Referenced 报告已写入: %s\n", one_md);
            printf("REPORT_MD=%s\n", one_md);
            if (one_jsonl_ptr != NULL) printf("REPORT_JSONL=%s\n", one_jsonl_ptr);
            ok_count++;
        }
    }
    return ok_count == pid_count ? 0 : 2;
}
