# Linux L0.2 validation

- date: 2026-07-31T09:37:00+08:00
- branch: main

..............
----------------------------------------------------------------------
Ran 14 tests in 0.085s

OK
-- The C compiler identification is GNU 11.4.0
-- Detecting C compiler ABI info
-- Detecting C compiler ABI info - done
-- Check for working C compiler: /usr/bin/cc - skipped
-- Detecting C compile features
-- Detecting C compile features - done
-- Looking for pthread.h
-- Looking for pthread.h - found
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD - Success
-- Found Threads: TRUE
-- Configuring done
-- Generating done
-- Build files have been written to: /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/default
[  2%] Building C object CMakeFiles/reclaim_core.dir/src/core/domain.c.o
[  4%] Building C object CMakeFiles/reclaim_core.dir/src/core/types.c.o
[  6%] Building C object CMakeFiles/reclaim_core.dir/src/core/engine.c.o
[  9%] Building C object CMakeFiles/reclaim_core.dir/src/core/lru.c.o
[ 11%] Building C object CMakeFiles/reclaim_core.dir/src/core/hash.c.o
[ 13%] Building C object CMakeFiles/reclaim_core.dir/src/core/list.c.o
[ 16%] Building C object CMakeFiles/reclaim_core.dir/src/core/stats.c.o
[ 18%] Building C object CMakeFiles/reclaim_core.dir/src/core/page.c.o
[ 20%] Building C object CMakeFiles/reclaim_core.dir/src/core/reclaim.c.o
[ 23%] Building C object CMakeFiles/reclaim_core.dir/src/core/aging_g1.c.o
[ 25%] Building C object CMakeFiles/reclaim_core.dir/src/core/validator.c.o
[ 30%] Building C object CMakeFiles/reclaim_core.dir/src/core/shadow_lru.c.o
[ 27%] Building C object CMakeFiles/reclaim_core.dir/src/core/scan_pressure.c.o
[ 32%] Building C object CMakeFiles/reclaim_core.dir/src/l02/shadow_alignment.c.o
[ 34%] Building C object CMakeFiles/reclaim_core.dir/src/l02/lruvec_trace_parser.c.o
[ 39%] Building C object CMakeFiles/reclaim_core.dir/src/l02/bootstrap_aggregate.c.o
[ 37%] Building C object CMakeFiles/reclaim_core.dir/src/l02/kernel_snapshot_store.c.o
[ 41%] Linking C static library libreclaim_core.a
[ 41%] Built target reclaim_core
[ 44%] Building C object CMakeFiles/lruvec_observer_cli.dir/tools/lruvec_observer_cli.c.o
[ 46%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/event_parser.c.o
[ 48%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/userspace_platform.c.o
[ 51%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/event_runner.c.o
[ 53%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/simulator_executor.c.o
[ 55%] Linking C static library libreclaim_userspace.a
[ 58%] Linking C executable bin/lruvec_observer_cli
[ 58%] Built target reclaim_userspace
[ 58%] Built target lruvec_observer_cli
[ 60%] Building C object CMakeFiles/reclaim_tests.dir/tests/test_support/test.c.o
[ 62%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_list.c.o
[ 65%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_reclaim.c.o
[ 67%] Building C object CMakeFiles/reclaim_simulator.dir/src/simulator/main.c.o
[ 69%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_types.c.o
[ 72%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_executor_outcomes.c.o
[ 74%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_policy.c.o
[ 76%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_engine.c.o
[ 79%] Building C object CMakeFiles/reclaim_tests.dir/tests/scenarios/test_trace.c.o
[ 81%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_lruvec_trace_parser.c.o
[ 83%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_shadow_lru.c.o
[ 86%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_kernel_snapshot_store.c.o
[ 88%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_reclaim_failures.c.o
[ 90%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_validation_corruption.c.o
[ 93%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_bootstrap_aggregate.c.o
[ 95%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_shadow_alignment.c.o
[ 97%] Linking C executable bin/reclaim_simulator
[ 97%] Built target reclaim_simulator
[100%] Linking C executable bin/reclaim_tests
[100%] Built target reclaim_tests
Internal ctest changing into directory: /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/default
Test project /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/default
    Start 1: reclaim_tests
1/1 Test #1: reclaim_tests ....................   Passed    0.15 sec

100% tests passed, 0 tests failed out of 1

Total Test time (real) =   0.15 sec
-- The C compiler identification is GNU 11.4.0
-- Detecting C compiler ABI info
-- Detecting C compiler ABI info - done
-- Check for working C compiler: /usr/bin/cc - skipped
-- Detecting C compile features
-- Detecting C compile features - done
-- Looking for pthread.h
-- Looking for pthread.h - found
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD
-- Performing Test CMAKE_HAVE_LIBC_PTHREAD - Success
-- Found Threads: TRUE
-- Performing Test RECLAIM_HAS_SANITIZERS
-- Performing Test RECLAIM_HAS_SANITIZERS - Success
-- Configuring done
-- Generating done
-- Build files have been written to: /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/asan
[  2%] Building C object CMakeFiles/reclaim_core.dir/src/core/list.c.o
[  4%] Building C object CMakeFiles/reclaim_core.dir/src/core/lru.c.o
[  6%] Building C object CMakeFiles/reclaim_core.dir/src/core/page.c.o
[  9%] Building C object CMakeFiles/reclaim_core.dir/src/core/types.c.o
[ 11%] Building C object CMakeFiles/reclaim_core.dir/src/core/engine.c.o
[ 13%] Building C object CMakeFiles/reclaim_core.dir/src/core/domain.c.o
[ 16%] Building C object CMakeFiles/reclaim_core.dir/src/core/hash.c.o
[ 18%] Building C object CMakeFiles/reclaim_core.dir/src/core/aging_g1.c.o
[ 20%] Building C object CMakeFiles/reclaim_core.dir/src/core/scan_pressure.c.o
[ 23%] Building C object CMakeFiles/reclaim_core.dir/src/core/stats.c.o
[ 27%] Building C object CMakeFiles/reclaim_core.dir/src/core/shadow_lru.c.o
[ 30%] Building C object CMakeFiles/reclaim_core.dir/src/l02/kernel_snapshot_store.c.o
[ 25%] Building C object CMakeFiles/reclaim_core.dir/src/core/validator.c.o
[ 32%] Building C object CMakeFiles/reclaim_core.dir/src/l02/bootstrap_aggregate.c.o
[ 34%] Building C object CMakeFiles/reclaim_core.dir/src/l02/shadow_alignment.c.o
[ 37%] Building C object CMakeFiles/reclaim_core.dir/src/core/reclaim.c.o
[ 39%] Building C object CMakeFiles/reclaim_core.dir/src/l02/lruvec_trace_parser.c.o
[ 41%] Linking C static library libreclaim_core.a
[ 41%] Built target reclaim_core
[ 44%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/simulator_executor.c.o
[ 46%] Building C object CMakeFiles/lruvec_observer_cli.dir/tools/lruvec_observer_cli.c.o
[ 48%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/userspace_platform.c.o
[ 51%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/event_parser.c.o
[ 53%] Building C object CMakeFiles/reclaim_userspace.dir/src/simulator/event_runner.c.o
[ 55%] Linking C executable bin/lruvec_observer_cli
[ 58%] Linking C static library libreclaim_userspace.a
[ 58%] Built target reclaim_userspace
[ 60%] Building C object CMakeFiles/reclaim_simulator.dir/src/simulator/main.c.o
[ 60%] Built target lruvec_observer_cli
[ 62%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_list.c.o
[ 65%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_engine.c.o
[ 67%] Building C object CMakeFiles/reclaim_tests.dir/tests/test_support/test.c.o
[ 69%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_types.c.o
[ 74%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_reclaim.c.o
[ 72%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_policy.c.o
[ 76%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_executor_outcomes.c.o
[ 79%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_reclaim_failures.c.o
[ 83%] Building C object CMakeFiles/reclaim_tests.dir/tests/scenarios/test_trace.c.o
[ 83%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_validation_corruption.c.o
[ 86%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_bootstrap_aggregate.c.o
[ 88%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_kernel_snapshot_store.c.o
[ 93%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_lruvec_trace_parser.c.o
[ 90%] Building C object CMakeFiles/reclaim_tests.dir/tests/unit/test_shadow_alignment.c.o
[ 95%] Building C object CMakeFiles/reclaim_tests.dir/tests/integration/test_shadow_lru.c.o
[ 97%] Linking C executable bin/reclaim_simulator
[ 97%] Built target reclaim_simulator
[100%] Linking C executable bin/reclaim_tests
[100%] Built target reclaim_tests
Internal ctest changing into directory: /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/asan
Test project /home/lzx/Desktop/huawei/myself-kswapd/用户态模拟器/v1/output/task19/asan
    Start 1: reclaim_tests
1/1 Test #1: reclaim_tests ....................   Passed    0.35 sec

100% tests passed, 0 tests failed out of 1

Total Test time (real) =   0.35 sec
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
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-long.h
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-n-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-n-debug-y: building trace.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-n-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-n-debug-y: PASS
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-long.h
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-n-lru-n-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-n-lru-n-debug-y: building trace.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-n-lru-n-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-n-lru-n-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-n-lru-n-debug-y: PASS
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-long.h
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-y-debug-y: building observer_config.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-y-debug-y: building trace.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-y-debug-y: building built-in.a
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-memcg-y-lru-y-debug-y'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel memcg-y-lru-y-debug-y: PASS
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
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
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-arch-fallback.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-instrumented.h
  CHKSHA1 /tmp/tmp.UT6ygkNAYH/Linux6.17/include/linux/atomic/atomic-long.h
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
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel debugfs-n: building observer_config.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/adapter/lruvec_sample.o
  CC      mm/myself_kswapd/heartbeat.o
  CC      mm/myself_kswapd/debugfs/lruvec_debugfs.o
  CC      mm/myself_kswapd/tests/lruvec_observer_test.o
  CC      mm/myself_kswapd/adapter/observer_config.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel debugfs-n: building trace.o
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
  CC      mm/myself_kswapd/trace/trace.o
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel debugfs-n: building built-in.a
make: Entering directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
make[1]: Entering directory '/tmp/myself-kswapd-l02-debugfs-n'
  GEN     Makefile
  CALL    /tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/checksyscalls.sh
  DESCEND objtool
  INSTALL libsubcmd_headers
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:549: warning: overriding recipe for target 'mm/myself_kswapd/built-in.a'
/tmp/tmp.UT6ygkNAYH/Linux6.17/scripts/Makefile.build:458: warning: ignoring old recipe for target 'mm/myself_kswapd/built-in.a'
  AR      mm/myself_kswapd/debugfs/built-in.a
  CC      mm/myself_kswapd/adapter/kswapd_observer.o
  CC      mm/myself_kswapd/adapter/lruvec_observer.o
  AR      mm/myself_kswapd/built-in.a
make[1]: Leaving directory '/tmp/myself-kswapd-l02-debugfs-n'
make: Leaving directory '/tmp/tmp.UT6ygkNAYH/Linux6.17'
kernel debugfs-n: PASS
bootstrapped /tmp/tmp.bpDKBXT3sY/dest from /tmp/tmp.bpDKBXT3sY/source
destination must be absent or empty: /tmp/tmp.bpDKBXT3sY/unknown
source and destination must differ: /tmp/tmp.bpDKBXT3sY/source
bootstrap self-test passed
refreshed /tmp/tmp.CRRikpc1AY/0003.patch
no allowlisted Linux6.17 differences
created empty /tmp/tmp.CRRikpc1AY/empty.patch
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
