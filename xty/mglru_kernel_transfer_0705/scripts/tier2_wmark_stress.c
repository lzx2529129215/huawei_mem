/*
 * Tier-2 Watermark Stress Test
 * Allocates anonymous memory, touches pages, creates memory pressure.
 * Usage: tier2_wmark_stress --mb <N> --seconds <N> [--hot-ratio <0-100>] [--sleep-us <N>]
 */

#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/mman.h>
#include <sys/time.h>
#include <time.h>
#include <errno.h>
#include <signal.h>

static volatile sig_atomic_t keep_running = 1;

static void sig_handler(int sig)
{
	(void)sig;
	keep_running = 0;
}

static double time_now(void)
{
	struct timeval tv;
	gettimeofday(&tv, NULL);
	return tv.tv_sec + tv.tv_usec / 1000000.0;
}

int main(int argc, char *argv[])
{
	unsigned long mb = 256;
	unsigned int duration_sec = 60;
	unsigned int hot_ratio = 30; /* percent */
	unsigned int sleep_us = 10000;
	char *mem = NULL;
	unsigned long nr_pages, hot_pages;
	unsigned long i;
	double start, now;

	/* Parse args */
	for (i = 1; i < (unsigned long)argc; i++) {
		if (!strcmp(argv[i], "--mb") && i + 1 < (unsigned long)argc)
			mb = strtoul(argv[++i], NULL, 0);
		else if (!strcmp(argv[i], "--seconds") && i + 1 < (unsigned long)argc)
			duration_sec = (unsigned int)strtoul(argv[++i], NULL, 0);
		else if (!strcmp(argv[i], "--hot-ratio") && i + 1 < (unsigned long)argc)
			hot_ratio = (unsigned int)strtoul(argv[++i], NULL, 0);
		else if (!strcmp(argv[i], "--sleep-us") && i + 1 < (unsigned long)argc)
			sleep_us = (unsigned int)strtoul(argv[++i], NULL, 0);
		else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
			printf("Usage: %s [--mb N] [--seconds N] [--hot-ratio 0-100] [--sleep-us N]\n", argv[0]);
			return 0;
		}
	}

	if (hot_ratio > 100)
		hot_ratio = 100;

	nr_pages = (mb * 1024 * 1024) / getpagesize();
	hot_pages = nr_pages * hot_ratio / 100;

	printf("Tier-2 Watermark Stress Test\n");
	printf("  Memory: %lu MB (%lu pages)\n", mb, nr_pages);
	printf("  Duration: %u seconds\n", duration_sec);
	printf("  Hot ratio: %u%% (%lu pages always touched)\n", hot_ratio, hot_pages);
	printf("  Sleep: %u us between touch rounds\n", sleep_us);
	printf("  Page size: %d bytes\n", getpagesize());

	/* Allocate anonymous memory */
	mem = mmap(NULL, nr_pages * getpagesize(),
		   PROT_READ | PROT_WRITE,
		   MAP_PRIVATE | MAP_ANONYMOUS,
		   -1, 0);

	if (mem == MAP_FAILED) {
		perror("mmap");
		fprintf(stderr, "Try reducing --mb (available memory may be limited)\n");
		return 1;
	}

	printf("Memory allocated at %p\n", (void *)mem);

	/* Set signal handler */
	signal(SIGINT, sig_handler);
	signal(SIGTERM, sig_handler);
	signal(SIGALRM, sig_handler);

	if (duration_sec > 0)
		alarm(duration_sec);

	start = time_now();
	printf("Starting stress loop at %.1f...\n", start);

	/* Stress loop: touch hot pages every round, cold pages less frequently */
	unsigned long round = 0;

	while (keep_running) {
		/* Touch hot pages every round */
		for (i = 0; i < hot_pages && keep_running; i++) {
			mem[i * getpagesize()] = (char)(i & 0xFF);
		}

		/* Touch cold pages every 10 rounds */
		if (round % 10 == 0) {
			for (i = hot_pages; i < nr_pages && keep_running; i++) {
				mem[i * getpagesize()] = (char)(i & 0xFF);
			}
		}

		round++;

		/* Report every 100 rounds */
		if (round % 100 == 0) {
			now = time_now();
			printf("[%.1f] Round %lu, %.1f seconds elapsed\n",
			       now, round, now - start);
		}

		if (sleep_us > 0)
			usleep(sleep_us);

		/* Check if duration has elapsed */
		now = time_now();
		if (duration_sec > 0 && (now - start) >= (double)duration_sec)
			break;
	}

	now = time_now();
	printf("Stress loop ended at %.1f (%.1f seconds, %lu rounds)\n",
	       now, now - start, round);

	/* Cleanup */
	if (mem != MAP_FAILED)
		munmap(mem, nr_pages * getpagesize());

	printf("Done.\n");
	return 0;
}
