#!/bin/bash

graph_data () {
	PAGESIZE=`getconf PAGESIZE`
	echo "#,orig_data_size,saved_size,compr_data_size,overhead,mem_used_max,same_pages,pages_compacted,huge_pages"
	for I in /sys/block/zram*/mm_stat
	do
		BD=${I#/sys/block/}
		BD=${BD%*/mm_stat}
		read orig_data_size compr_data_size mem_used_total mem_limit mem_used_max same_pages pages_compacted huge_pages < "$I"
		echo "$BD,$orig_data_size,$(($orig_data_size-$compr_data_size)),$compr_data_size,$(($mem_used_total-$compr_data_size)),$mem_limit,$mem_used_max,$(($same_pages*$PAGESIZE)),$(($pages_compacted*$PAGESIZE)),$(($huge_pages*$PAGESIZE))"
	done
}

F=`mktemp zram-stats.XXXXXX`
graph_data > $F
cat $F
gnuplot -p -e "\
set title 'ZRAM'; \
set key right outside; \
set style data histograms; \
set style histogram rowstacked; \
set boxwidth 0.5; \
set xtics rotate; \
set format y '%.0s%cB'; \
set style fill solid 1.0 border -1; \
set datafile separator ','; \
plot '$F' using 8:xtic(1) t 'Same bytes', '' using 9 t 'Compacted bytes', '' using 10 t 'Huge bytes', '' using 5 t 'Overhead bytes', '' using 3 t 'Saved bytes'"
rm -f $F
