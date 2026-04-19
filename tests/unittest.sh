#!/bin/bash
# Vendored from MicroPythonOS/tests/unittest.sh so the LightningPiggy test
# suite is self-contained and doesn't depend on the MicroPythonOS repo
# layout. Kept as close to upstream as practical to ease future sync.
#
# Changes vs upstream:
#   - MicroPythonOS checkout discovered via $MPOS_HOME (env var) with a
#     ../MicroPythonOS sibling-directory default, instead of hardcoded
#     relative paths.
#   - The Lightning Piggy assets/ dir is auto-injected into sys.path so
#     tests can `import wallet_cache` etc. without manual path hacks.

mydir=$(readlink -f "$0")
mydir=$(dirname "$mydir")
testdir="$mydir"

# Locate the MicroPythonOS checkout (needed for the desktop binary,
# internal_filesystem, and mpremote). Precedence:
#   1. $MPOS_HOME env var
#   2. ../MicroPythonOS (sibling layout: /parent/{LightningPiggyApp,MicroPythonOS})
if [ -n "$MPOS_HOME" ]; then
	mpos=$(readlink -f "$MPOS_HOME")
elif [ -d "$mydir/../../MicroPythonOS" ]; then
	mpos=$(readlink -f "$mydir/../../MicroPythonOS")
else
	echo "ERROR: MicroPythonOS checkout not found."
	echo "Set \$MPOS_HOME, or clone MicroPythonOS as a sibling of LightningPiggyApp."
	exit 1
fi

scriptdir="$mpos/scripts"
fs="$mpos/internal_filesystem"
mpremote="$mpos/lvgl_micropython/lib/micropython/tools/mpremote/mpremote.py"
#heapsize=8M
heapsize=16M # on desktop, a bit more is warranted (different C library etc)

# The Lightning Piggy app's assets/ dir — auto-injected into sys.path so
# tests can `from payment import Payment`, `import wallet_cache`, etc.
lp_assets=$(readlink -f "$mydir/../com.lightningpiggy.displaywallet/assets")
if [ ! -d "$lp_assets" ]; then
	echo "ERROR: Lightning Piggy assets dir not found at $lp_assets"
	exit 1
fi

# Parse arguments
ondevice=""
onetest=""

while [ $# -gt 0 ]; do
    case "$1" in
        --ondevice)
            ondevice="yes"
            ;;
        *)
            onetest="$1"
            ;;
    esac
    shift
done

# print os and set binary
os_name=$(uname -s)
if [ "$os_name" = "Darwin" ]; then
        echo "Running on macOS"
        binary="$mpos"/lvgl_micropython/build/lvgl_micropy_macOS
else
        # other cases can be added here
        echo "Running on $os_name"
        binary="$mpos"/lvgl_micropython/build/lvgl_micropy_unix
fi

binary=$(readlink -f "$binary")
if [ ! -x "$binary" ]; then
	echo "ERROR: MicroPythonOS desktop binary not found/executable at $binary"
	echo "Build it first: cd $mpos && bash scripts/build_mpos.sh \$(uname -s | tr A-Z a-z)"
	exit 1
fi
chmod +x "$binary"

# make sure no autostart is configured:
rm -f "$fs"/data/com.micropythonos.settings/config.json

one_test() {
	file="$1"
	if [ ! -f "$file" ]; then
		echo "ERROR: $file is not a regular, existing file!"
		exit 1
	fi
	pushd "$fs"
	echo "Testing $file"

	# Detect if this is a graphical test (filename contains "graphical")
	if echo "$file" | grep -q "graphical"; then
		echo "Detected graphical test - including boot and main files"
		is_graphical=1
		# Get absolute path to tests directory for imports
		tests_abs_path=$(readlink -f "$testdir")
	else
		is_graphical=0
	fi

	if [ -z "$ondevice" ]; then
		# Desktop execution
		if [ $is_graphical -eq 1 ]; then
			echo "Graphical test: include main.py"
			"$binary" -X heapsize=$heapsize -c "import sys ; sys.path.insert(0, 'lib') ; sys.path.append(\"$tests_abs_path\") ; sys.path.append(\"$lp_assets\") ; import mpos ; mpos.TaskManager.disable() ; $(cat main.py)
$(cat $file)
result = unittest.main() ; sys.exit(0 if result.wasSuccessful() else 1) "
	           result=$?
		else
			echo "Regular test: no boot files"
			"$binary" -X heapsize=$heapsize -c "import sys ; sys.path.insert(0, 'lib') ; sys.path.append(\"$lp_assets\") ; import mpos ; mpos.TaskManager.disable() ; $(cat main.py)
$(cat $file)
result = unittest.main() ; sys.exit(0 if result.wasSuccessful() else 1) "
	           result=$?
		fi
	else
		if [ ! -z "$ondevice" ]; then
			echo "Hack: reset the device to make sure no previous UnitTest classes have been registered..."
			"$mpremote" reset
			sleep 30
		fi

		echo "Device execution"
		# NOTE: On device, the OS is already running with boot.py and main.py executed,
		# so we don't need to (and shouldn't) re-run them. The system is already initialized.
		# Lightning Piggy assets live at /apps/com.lightningpiggy.displaywallet/assets/
		# on device — use that path instead of $lp_assets (which is host-side).
		cleanname=$(echo "$file" | sed "s#/#_#g")
		testlog=/tmp/"$cleanname".log
		echo "$test logging to $testlog"
		if [ $is_graphical -eq 1 ]; then
			# Graphical test: system already initialized, just add test paths
			"$mpremote" exec "import sys ; sys.path.insert(0, 'lib') ; sys.path.append('tests') ; sys.path.append('apps/com.lightningpiggy.displaywallet/assets') ; import mpos ; mpos.TaskManager.disable() ; $(cat main.py)
$(cat $file)
result = unittest.main()
if result.wasSuccessful():
		  print('TEST WAS A SUCCESS')
else:
		  print('TEST WAS A FAILURE')
" | tee "$testlog"
		else
			# Regular test: no boot files
			"$mpremote" exec "import sys ; sys.path.insert(0, 'lib') ; sys.path.append('tests') ; sys.path.append('apps/com.lightningpiggy.displaywallet/assets') ; import mpos ; mpos.TaskManager.disable() ; $(cat main.py)
$(cat $file)
result = unittest.main()
if result.wasSuccessful():
		  print('TEST WAS A SUCCESS')
else:
		  print('TEST WAS A FAILURE')
" | tee "$testlog"
		fi
		grep -q "TEST WAS A SUCCESS" "$testlog"
		result=$?
	fi
	popd
	return "$result"
}

failed=0
ran=0

if [ -z "$onetest" ]; then
	echo "Usage: $0 [one_test_to_run.py] [--ondevice]"
	echo "Example: $0 tests/test_onchain_wallet.py"
	echo "Example: $0 tests/test_onchain_wallet.py --ondevice"
	echo "Example: $0 --ondevice"
	echo
	echo "If no test is specified: run all tests from $testdir on local machine."
	echo
	echo "The '--ondevice' flag will run the test(s) on a connected device using mpremote.py over a serial connection."
	echo
	echo "MicroPythonOS checkout resolved to: $mpos"
	echo "Lightning Piggy assets resolved to: $lp_assets"
	files=$(find "$testdir" -iname "test_*.py" )
	for file in $files; do
		one_test "$file"
		result=$?
		if [ $result -ne 0 ]; then
			echo -e "\n\n\nWARNING: test $file got error $result !!!\n\n\n"
			failed=$(expr $failed \+ 1)
			exit 1
		else
			ran=$(expr $ran \+ 1)
		fi
	done
else
	echo "doing $onetest"
	one_test $(readlink -f "$onetest")
	result=$?
	if [ $result -ne 0 ]; then
		echo "Test returned result: $result"
		failed=1
	fi
fi


if [ $failed -ne 0 ]; then
        echo "ERROR: $failed of the $ran tests failed"
        exit 1
else
	echo "GOOD: none of the $ran tests failed"
	exit 0
fi
