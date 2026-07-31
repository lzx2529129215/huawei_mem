# Linux L0.2 validation

## Tracepoint T1 buildability repair

- Root cause: the three custom trace events had 27, 23, and 25 producer
  arguments while Linux 6.17's BPF tracepoint path supports at most 12.
  COUNT_ARGS therefore treated the sixteenth business argument as a count,
  producing identifiers such as bpf_trace_runboost_active.
- RED: test_trace_event_arg_limits.py failed only for
  priority_round=27, request_end=23, and lruvec_snapshot=25;
  request_begin=7 already passed.
- Repair: producer parameters are now 8, 4, and 1 respectively, using only
  existing context/snapshot objects and computed scalars. Event names, entry
  field names/types/order, and TP_printk format/key/argument order are
  unchanged. The independent text-ABI comparison passed.
- Build evidence: the development-tree trace.o and the final patch-applied
  observer_config.o, heartbeat.o, trace.o, and
  mm/myself_kswapd/built-in.a all passed.
- Parser evidence: 14 Python parser tests passed; existing fixtures were not
  changed. User-space CTest passed and the aggregate test binary reported
  42/42 passed.
- Gate evidence: check_l02.sh passed for MEMCG=y/LRU_GEN=n,
  MEMCG=n/LRU_GEN=n, MEMCG=y/LRU_GEN=y, and DEBUG_FS=n. It now checks the
  producer-argument limit and explicitly builds trace.o before built-in.a
  in the final patch-applied tree.
- Scope: bzImage/modules, installation, and runtime smoke were not run.

- date: 2026-07-30T17:37:04+08:00
- branch: feat/linux-l02-lruvec-observer

..............
----------------------------------------------------------------------
Ran 14 tests in 0.078s

OK
-- Configuring done
-- Generating done
-- Build files have been written to: /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/default
Consolidate compiler generated dependencies of target reclaim_core
[ 41%] Built target reclaim_core
Consolidate compiler generated dependencies of target lruvec_observer_cli
Consolidate compiler generated dependencies of target reclaim_userspace
[ 51%] Built target lruvec_observer_cli
[ 58%] Built target reclaim_userspace
Consolidate compiler generated dependencies of target reclaim_simulator
Consolidate compiler generated dependencies of target reclaim_tests
[ 62%] Built target reclaim_simulator
[100%] Built target reclaim_tests
Internal ctest changing into directory: /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/default
Test project /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/default
    Start 1: reclaim_tests
1/1 Test #1: reclaim_tests ....................   Passed    0.18 sec

100% tests passed, 0 tests failed out of 1

Total Test time (real) =   0.18 sec
-- Configuring done
-- Generating done
-- Build files have been written to: /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/asan
Consolidate compiler generated dependencies of target reclaim_core
[ 41%] Built target reclaim_core
Consolidate compiler generated dependencies of target lruvec_observer_cli
Consolidate compiler generated dependencies of target reclaim_userspace
[ 46%] Built target lruvec_observer_cli
[ 58%] Built target reclaim_userspace
Consolidate compiler generated dependencies of target reclaim_simulator
Consolidate compiler generated dependencies of target reclaim_tests
[100%] Built target reclaim_tests
[ 67%] Built target reclaim_simulator
Internal ctest changing into directory: /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/asan
Test project /home/lzx/Desktop/huawei/myself-kswapd-l02/用户态模拟器/v1/output/task19/asan
    Start 1: reclaim_tests
1/1 Test #1: reclaim_tests ....................   Passed    0.33 sec

100% tests passed, 0 tests failed out of 1

Total Test time (real) =   0.33 sec
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
42/42 tests passed
100-run user-space tests: PASS
myself_kswapd_request_begin: proto=7 args=7
myself_kswapd_priority_round: proto=8 args=8
myself_kswapd_request_end: proto=4 args=4
lruvec_snapshot: proto=1 args=1
PASS: all custom trace events have <= 12 producer arguments
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  HOSTCC  scripts/basic/fixdep
  HOSTCC  scripts/kconfig/conf.o
  HOSTCC  scripts/kconfig/confdata.o
  HOSTCC  scripts/kconfig/expr.o
  LEX     scripts/kconfig/lexer.lex.c
  YACC    scripts/kconfig/parser.tab.[ch]
  HOSTCC  scripts/kconfig/lexer.lex.o
  HOSTCC  scripts/kconfig/menu.o
  HOSTCC  scripts/kconfig/parser.tab.o
  HOSTCC  scripts/kconfig/preprocess.o
  HOSTCC  scripts/kconfig/symbol.o
  HOSTCC  scripts/kconfig/util.o
  HOSTLD  scripts/kconfig/conf
*** Default configuration is based on 'x86_64_defconfig'
#
# configuration written to .config
#
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
#
# configuration written to .config
#
  SYNC    include/config/auto.conf.cmd
  GEN     Makefile
  GEN     Makefile
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_32.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_64.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_32_ia32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_64_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_64.h
  HOSTCC  arch/x86/tools/relocs_32.o
  HOSTCC  arch/x86/tools/relocs_64.o
  HOSTCC  arch/x86/tools/relocs_common.o
  HOSTLD  arch/x86/tools/relocs
  HOSTCC  scripts/selinux/mdp/mdp
  HOSTCC  scripts/kallsyms
  HOSTCC  scripts/sorttable
  HOSTCC  scripts/asn1_compiler
  WRAP    arch/x86/include/generated/uapi/asm/bpf_perf_event.h
  WRAP    arch/x86/include/generated/uapi/asm/errno.h
  WRAP    arch/x86/include/generated/uapi/asm/fcntl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctls.h
  WRAP    arch/x86/include/generated/uapi/asm/ipcbuf.h
  WRAP    arch/x86/include/generated/uapi/asm/param.h
  WRAP    arch/x86/include/generated/uapi/asm/poll.h
  WRAP    arch/x86/include/generated/uapi/asm/resource.h
  WRAP    arch/x86/include/generated/uapi/asm/socket.h
  WRAP    arch/x86/include/generated/uapi/asm/sockios.h
  WRAP    arch/x86/include/generated/uapi/asm/termbits.h
  WRAP    arch/x86/include/generated/uapi/asm/termios.h
  WRAP    arch/x86/include/generated/uapi/asm/types.h
  WRAP    arch/x86/include/generated/asm/early_ioremap.h
  WRAP    arch/x86/include/generated/asm/fprobe.h
  WRAP    arch/x86/include/generated/asm/mcs_spinlock.h
  WRAP    arch/x86/include/generated/asm/mmzone.h
  WRAP    arch/x86/include/generated/asm/irq_regs.h
  WRAP    arch/x86/include/generated/asm/kmap_size.h
  WRAP    arch/x86/include/generated/asm/local64.h
  WRAP    arch/x86/include/generated/asm/mmiowb.h
  WRAP    arch/x86/include/generated/asm/module.lds.h
  WRAP    arch/x86/include/generated/asm/rwonce.h
  WRAP    arch/x86/include/generated/asm/unwind_user.h
  UPD     arch/x86/include/generated/asm/cpufeaturemasks.h
  GEN     arch/x86/include/generated/asm/orc_hash.h
  UPD     include/config/kernel.release
  UPD     include/generated/uapi/linux/version.h
  UPD     include/generated/utsrelease.h
  UPD     include/generated/compile.h
  CC      scripts/mod/empty.o
  HOSTCC  scripts/mod/mk_elfconfig
  MKELF   scripts/mod/elfconfig.h
  HOSTCC  scripts/mod/modpost.o
  CC      scripts/mod/devicetable-offsets.s
  UPD     scripts/mod/devicetable-offsets.h
  HOSTCC  scripts/mod/file2alias.o
  HOSTCC  scripts/mod/sumversion.o
  HOSTCC  scripts/mod/symsearch.o
  HOSTLD  scripts/mod/modpost
  UPD     include/generated/timeconst.h
  CC      kernel/bounds.s
  UPD     include/generated/bounds.h
  CC      arch/x86/kernel/asm-offsets.s
  UPD     include/generated/asm-offsets.h
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-long.h
  DESCEND objtool
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/exec-cmd.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/help.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/pager.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/parse-options.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/run-command.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/sigchain.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/subcmd-config.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/libsubcmd-in.o
  AR      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/libsubcmd.a
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/exec-cmd.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/help.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/pager.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/parse-options.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/run-command.h
  INSTALL libsubcmd_headers
  MKDIR   /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/special.o
  MKDIR   /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/lib/
  GEN     /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/lib/inat-tables.c
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/decode.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/orc.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/arch/x86/objtool-in.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/weak.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/check.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/special.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/builtin-check.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/elf.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/objtool.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/orc_gen.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/orc_dump.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libstring.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/libctype.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/str_error_r.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/librbtree.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/objtool-in.o
  LINK    /tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y/tools/objtool/objtool
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-n-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-n-debug-y: building trace.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-n-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-n-debug-y: PASS
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  HOSTCC  scripts/basic/fixdep
  HOSTCC  scripts/kconfig/conf.o
  HOSTCC  scripts/kconfig/confdata.o
  HOSTCC  scripts/kconfig/expr.o
  LEX     scripts/kconfig/lexer.lex.c
  YACC    scripts/kconfig/parser.tab.[ch]
  HOSTCC  scripts/kconfig/lexer.lex.o
  HOSTCC  scripts/kconfig/menu.o
  HOSTCC  scripts/kconfig/parser.tab.o
  HOSTCC  scripts/kconfig/preprocess.o
  HOSTCC  scripts/kconfig/symbol.o
  HOSTCC  scripts/kconfig/util.o
  HOSTLD  scripts/kconfig/conf
*** Default configuration is based on 'x86_64_defconfig'
#
# configuration written to .config
#
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
#
# configuration written to .config
#
  SYNC    include/config/auto.conf.cmd
  GEN     Makefile
  GEN     Makefile
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_32.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_64.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_32_ia32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_64_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_64.h
  HOSTCC  arch/x86/tools/relocs_32.o
  HOSTCC  arch/x86/tools/relocs_64.o
  HOSTCC  arch/x86/tools/relocs_common.o
  HOSTLD  arch/x86/tools/relocs
  HOSTCC  scripts/selinux/mdp/mdp
  HOSTCC  scripts/kallsyms
  HOSTCC  scripts/sorttable
  HOSTCC  scripts/asn1_compiler
  WRAP    arch/x86/include/generated/uapi/asm/bpf_perf_event.h
  WRAP    arch/x86/include/generated/uapi/asm/errno.h
  WRAP    arch/x86/include/generated/uapi/asm/fcntl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctls.h
  WRAP    arch/x86/include/generated/uapi/asm/ipcbuf.h
  WRAP    arch/x86/include/generated/uapi/asm/param.h
  WRAP    arch/x86/include/generated/uapi/asm/poll.h
  WRAP    arch/x86/include/generated/uapi/asm/resource.h
  WRAP    arch/x86/include/generated/uapi/asm/socket.h
  WRAP    arch/x86/include/generated/uapi/asm/sockios.h
  WRAP    arch/x86/include/generated/uapi/asm/termbits.h
  WRAP    arch/x86/include/generated/uapi/asm/termios.h
  WRAP    arch/x86/include/generated/uapi/asm/types.h
  WRAP    arch/x86/include/generated/asm/early_ioremap.h
  WRAP    arch/x86/include/generated/asm/fprobe.h
  WRAP    arch/x86/include/generated/asm/mcs_spinlock.h
  WRAP    arch/x86/include/generated/asm/mmzone.h
  WRAP    arch/x86/include/generated/asm/irq_regs.h
  WRAP    arch/x86/include/generated/asm/kmap_size.h
  WRAP    arch/x86/include/generated/asm/local64.h
  WRAP    arch/x86/include/generated/asm/mmiowb.h
  WRAP    arch/x86/include/generated/asm/module.lds.h
  WRAP    arch/x86/include/generated/asm/rwonce.h
  WRAP    arch/x86/include/generated/asm/unwind_user.h
  UPD     arch/x86/include/generated/asm/cpufeaturemasks.h
  GEN     arch/x86/include/generated/asm/orc_hash.h
  UPD     include/config/kernel.release
  UPD     include/generated/uapi/linux/version.h
  UPD     include/generated/utsrelease.h
  UPD     include/generated/compile.h
  CC      scripts/mod/empty.o
  HOSTCC  scripts/mod/mk_elfconfig
  MKELF   scripts/mod/elfconfig.h
  HOSTCC  scripts/mod/modpost.o
  CC      scripts/mod/devicetable-offsets.s
  UPD     scripts/mod/devicetable-offsets.h
  HOSTCC  scripts/mod/file2alias.o
  HOSTCC  scripts/mod/sumversion.o
  HOSTCC  scripts/mod/symsearch.o
  HOSTLD  scripts/mod/modpost
  UPD     include/generated/timeconst.h
  CC      kernel/bounds.s
  UPD     include/generated/bounds.h
  CC      arch/x86/kernel/asm-offsets.s
  UPD     include/generated/asm-offsets.h
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-long.h
  DESCEND objtool
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/exec-cmd.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/help.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/pager.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/parse-options.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/run-command.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/sigchain.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/subcmd-config.o
  LD      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/libsubcmd-in.o
  AR      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/libsubcmd.a
  INSTALL /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/exec-cmd.h
  INSTALL /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/help.h
  INSTALL /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/pager.h
  INSTALL /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/parse-options.h
  INSTALL /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libsubcmd/include/subcmd/run-command.h
  INSTALL libsubcmd_headers
  MKDIR   /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/special.o
  MKDIR   /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/lib/
  GEN     /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/lib/inat-tables.c
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/decode.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/orc.o
  LD      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/arch/x86/objtool-in.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/weak.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/check.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/special.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/builtin-check.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/elf.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/objtool.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/orc_gen.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/orc_dump.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libstring.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/libctype.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/str_error_r.o
  CC      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/librbtree.o
  LD      /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/objtool-in.o
  LINK    /tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y/tools/objtool/objtool
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-n-lru-n-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-n-lru-n-debug-y: building trace.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-n-lru-n-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-n-lru-n-debug-y: PASS
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  HOSTCC  scripts/basic/fixdep
  HOSTCC  scripts/kconfig/conf.o
  HOSTCC  scripts/kconfig/confdata.o
  HOSTCC  scripts/kconfig/expr.o
  LEX     scripts/kconfig/lexer.lex.c
  YACC    scripts/kconfig/parser.tab.[ch]
  HOSTCC  scripts/kconfig/lexer.lex.o
  HOSTCC  scripts/kconfig/menu.o
  HOSTCC  scripts/kconfig/parser.tab.o
  HOSTCC  scripts/kconfig/preprocess.o
  HOSTCC  scripts/kconfig/symbol.o
  HOSTCC  scripts/kconfig/util.o
  HOSTLD  scripts/kconfig/conf
*** Default configuration is based on 'x86_64_defconfig'
#
# configuration written to .config
#
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
#
# configuration written to .config
#
  SYNC    include/config/auto.conf.cmd
  GEN     Makefile
  GEN     Makefile
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_32.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_64.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_32_ia32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_64_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_64.h
  HOSTCC  arch/x86/tools/relocs_32.o
  HOSTCC  arch/x86/tools/relocs_64.o
  HOSTCC  arch/x86/tools/relocs_common.o
  HOSTLD  arch/x86/tools/relocs
  HOSTCC  scripts/selinux/mdp/mdp
  HOSTCC  scripts/kallsyms
  HOSTCC  scripts/sorttable
  HOSTCC  scripts/asn1_compiler
  WRAP    arch/x86/include/generated/uapi/asm/bpf_perf_event.h
  WRAP    arch/x86/include/generated/uapi/asm/errno.h
  WRAP    arch/x86/include/generated/uapi/asm/fcntl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctls.h
  WRAP    arch/x86/include/generated/uapi/asm/ipcbuf.h
  WRAP    arch/x86/include/generated/uapi/asm/param.h
  WRAP    arch/x86/include/generated/uapi/asm/poll.h
  WRAP    arch/x86/include/generated/uapi/asm/resource.h
  WRAP    arch/x86/include/generated/uapi/asm/socket.h
  WRAP    arch/x86/include/generated/uapi/asm/sockios.h
  WRAP    arch/x86/include/generated/uapi/asm/termbits.h
  WRAP    arch/x86/include/generated/uapi/asm/termios.h
  WRAP    arch/x86/include/generated/uapi/asm/types.h
  WRAP    arch/x86/include/generated/asm/early_ioremap.h
  WRAP    arch/x86/include/generated/asm/fprobe.h
  WRAP    arch/x86/include/generated/asm/mcs_spinlock.h
  WRAP    arch/x86/include/generated/asm/mmzone.h
  WRAP    arch/x86/include/generated/asm/irq_regs.h
  WRAP    arch/x86/include/generated/asm/kmap_size.h
  WRAP    arch/x86/include/generated/asm/local64.h
  WRAP    arch/x86/include/generated/asm/mmiowb.h
  WRAP    arch/x86/include/generated/asm/module.lds.h
  WRAP    arch/x86/include/generated/asm/rwonce.h
  WRAP    arch/x86/include/generated/asm/unwind_user.h
  UPD     arch/x86/include/generated/asm/cpufeaturemasks.h
  GEN     arch/x86/include/generated/asm/orc_hash.h
  UPD     include/config/kernel.release
  UPD     include/generated/uapi/linux/version.h
  UPD     include/generated/utsrelease.h
  UPD     include/generated/compile.h
  CC      scripts/mod/empty.o
  HOSTCC  scripts/mod/mk_elfconfig
  MKELF   scripts/mod/elfconfig.h
  HOSTCC  scripts/mod/modpost.o
  CC      scripts/mod/devicetable-offsets.s
  UPD     scripts/mod/devicetable-offsets.h
  HOSTCC  scripts/mod/file2alias.o
  HOSTCC  scripts/mod/sumversion.o
  HOSTCC  scripts/mod/symsearch.o
  HOSTLD  scripts/mod/modpost
  UPD     include/generated/timeconst.h
  CC      kernel/bounds.s
  UPD     include/generated/bounds.h
  CC      arch/x86/kernel/asm-offsets.s
  UPD     include/generated/asm-offsets.h
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-long.h
  DESCEND objtool
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/exec-cmd.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/help.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/pager.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/parse-options.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/run-command.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/sigchain.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/subcmd-config.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/libsubcmd-in.o
  AR      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/libsubcmd.a
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/include/subcmd/exec-cmd.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/include/subcmd/help.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/include/subcmd/pager.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/include/subcmd/parse-options.h
  INSTALL /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libsubcmd/include/subcmd/run-command.h
  INSTALL libsubcmd_headers
  MKDIR   /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/special.o
  MKDIR   /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/lib/
  GEN     /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/lib/inat-tables.c
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/decode.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/orc.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/arch/x86/objtool-in.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/weak.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/check.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/special.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/builtin-check.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/elf.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/objtool.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/orc_gen.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/orc_dump.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libstring.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/libctype.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/str_error_r.o
  CC      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/librbtree.o
  LD      /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/objtool-in.o
  LINK    /tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y/tools/objtool/objtool
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-y-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-y-debug-y: building trace.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-y-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel memcg-y-lru-y-debug-y: PASS
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  HOSTCC  scripts/basic/fixdep
  HOSTCC  scripts/kconfig/conf.o
  HOSTCC  scripts/kconfig/confdata.o
  HOSTCC  scripts/kconfig/expr.o
  LEX     scripts/kconfig/lexer.lex.c
  YACC    scripts/kconfig/parser.tab.[ch]
  HOSTCC  scripts/kconfig/lexer.lex.o
  HOSTCC  scripts/kconfig/menu.o
  HOSTCC  scripts/kconfig/parser.tab.o
  HOSTCC  scripts/kconfig/preprocess.o
  HOSTCC  scripts/kconfig/symbol.o
  HOSTCC  scripts/kconfig/util.o
  HOSTLD  scripts/kconfig/conf
*** Default configuration is based on 'x86_64_defconfig'
#
# configuration written to .config
#
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
#
# configuration written to .config
#
  SYNC    include/config/auto.conf.cmd
  GEN     Makefile
  GEN     Makefile
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_32.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_64.h
  SYSHDR  arch/x86/include/generated/uapi/asm/unistd_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_32_ia32.h
  SYSHDR  arch/x86/include/generated/asm/unistd_64_x32.h
  SYSTBL  arch/x86/include/generated/asm/syscalls_64.h
  HOSTCC  arch/x86/tools/relocs_32.o
  HOSTCC  arch/x86/tools/relocs_64.o
  HOSTCC  arch/x86/tools/relocs_common.o
  HOSTLD  arch/x86/tools/relocs
  HOSTCC  scripts/selinux/mdp/mdp
  HOSTCC  scripts/kallsyms
  HOSTCC  scripts/sorttable
  HOSTCC  scripts/asn1_compiler
  WRAP    arch/x86/include/generated/uapi/asm/bpf_perf_event.h
  WRAP    arch/x86/include/generated/uapi/asm/errno.h
  WRAP    arch/x86/include/generated/uapi/asm/fcntl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctl.h
  WRAP    arch/x86/include/generated/uapi/asm/ioctls.h
  WRAP    arch/x86/include/generated/uapi/asm/ipcbuf.h
  WRAP    arch/x86/include/generated/uapi/asm/param.h
  WRAP    arch/x86/include/generated/uapi/asm/poll.h
  WRAP    arch/x86/include/generated/uapi/asm/resource.h
  WRAP    arch/x86/include/generated/uapi/asm/socket.h
  WRAP    arch/x86/include/generated/uapi/asm/sockios.h
  WRAP    arch/x86/include/generated/uapi/asm/termbits.h
  WRAP    arch/x86/include/generated/uapi/asm/termios.h
  WRAP    arch/x86/include/generated/uapi/asm/types.h
  WRAP    arch/x86/include/generated/asm/early_ioremap.h
  WRAP    arch/x86/include/generated/asm/fprobe.h
  WRAP    arch/x86/include/generated/asm/mcs_spinlock.h
  WRAP    arch/x86/include/generated/asm/mmzone.h
  WRAP    arch/x86/include/generated/asm/irq_regs.h
  WRAP    arch/x86/include/generated/asm/kmap_size.h
  WRAP    arch/x86/include/generated/asm/local64.h
  WRAP    arch/x86/include/generated/asm/mmiowb.h
  WRAP    arch/x86/include/generated/asm/module.lds.h
  WRAP    arch/x86/include/generated/asm/rwonce.h
  WRAP    arch/x86/include/generated/asm/unwind_user.h
  UPD     arch/x86/include/generated/asm/cpufeaturemasks.h
  GEN     arch/x86/include/generated/asm/orc_hash.h
  UPD     include/config/kernel.release
  UPD     include/generated/uapi/linux/version.h
  UPD     include/generated/utsrelease.h
  UPD     include/generated/compile.h
  CC      scripts/mod/empty.o
  HOSTCC  scripts/mod/mk_elfconfig
  MKELF   scripts/mod/elfconfig.h
  HOSTCC  scripts/mod/modpost.o
  CC      scripts/mod/devicetable-offsets.s
  UPD     scripts/mod/devicetable-offsets.h
  HOSTCC  scripts/mod/file2alias.o
  HOSTCC  scripts/mod/sumversion.o
  HOSTCC  scripts/mod/symsearch.o
  HOSTLD  scripts/mod/modpost
  UPD     include/generated/timeconst.h
  CC      kernel/bounds.s
  UPD     include/generated/bounds.h
  CC      arch/x86/kernel/asm-offsets.s
  UPD     include/generated/asm-offsets.h
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.D8K7ri0DFB/Linux6.17/include/linux/atomic/atomic-long.h
  DESCEND objtool
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/exec-cmd.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/help.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/pager.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/parse-options.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/run-command.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/sigchain.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/subcmd-config.o
  LD      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/libsubcmd-in.o
  AR      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/libsubcmd.a
  INSTALL /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/include/subcmd/exec-cmd.h
  INSTALL /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/include/subcmd/help.h
  INSTALL /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/include/subcmd/pager.h
  INSTALL /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/include/subcmd/parse-options.h
  INSTALL /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libsubcmd/include/subcmd/run-command.h
  INSTALL libsubcmd_headers
  MKDIR   /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/special.o
  MKDIR   /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/lib/
  GEN     /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/lib/inat-tables.c
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/decode.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/orc.o
  LD      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/arch/x86/objtool-in.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/weak.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/check.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/special.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/builtin-check.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/elf.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/objtool.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/orc_gen.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/orc_dump.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libstring.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/libctype.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/str_error_r.o
  CC      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/librbtree.o
  LD      /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/objtool-in.o
  LINK    /tmp/myself-kswapd-l02-debugfs-n/tools/objtool/objtool
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel debugfs-n: building observer_config.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel debugfs-n: building trace.o
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel debugfs-n: building built-in.a
make: Entering directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.D8K7ri0DFB/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.D8K7ri0DFB/Linux6.17'
kernel debugfs-n: PASS
bootstrapped /tmp/tmp.ZUXYeQy2dl/dest from /tmp/tmp.ZUXYeQy2dl/source
destination must be absent or empty: /tmp/tmp.ZUXYeQy2dl/unknown
source and destination must differ: /tmp/tmp.ZUXYeQy2dl/source
bootstrap self-test passed
refreshed /tmp/tmp.OweI4lhzKC/0003.patch
no allowlisted Linux6.17 differences
created empty /tmp/tmp.OweI4lhzKC/empty.patch
patch refresh self-test passed
shell tests, syntax and diff check: PASS
validation complete

## Runtime smoke

- kernel: 6.17.13-mglru-dual-observe-damon-20260715
- tracefs: /sys/kernel/tracing
- MGLRU state: 0x0007

NOT RUN / ENVIRONMENT BLOCKED
- myself_kswapd trace events unavailable
- MGLRU state requires explicit --allow-disable-mglru for any change

## TSan

- build: PASS
- ctest: NOT RUN / ENVIRONMENT BLOCKED
- evidence: `FATAL: ThreadSanitizer: unexpected memory mapping 0x640da6d20000-0x640da6d22000`
