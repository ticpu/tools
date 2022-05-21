package main

import (
	"bufio"
	"context"
	"golang.org/x/sync/semaphore"
	"io"
	"os"
	"os/exec"
)

const (
	MaxProcesses       = 4
	MaxLinesPerProcess = 3
)

func subprocess(lines <-chan string, done *semaphore.Weighted) {
	defer done.Release(1)
	cmd := exec.Command(os.Args[1], os.Args[2:]...)
	pipe, _ := cmd.StdinPipe()
	cmd.Stdout = os.Stdout
	cmd.Stderr = os.Stderr
	_ = cmd.Start()
	for line := range lines {
		_, _ = io.WriteString(pipe, line+"\n")
	}
	_ = pipe.Close()
	_ = cmd.Wait()
}

func main() {
	var linesChannel chan string
	ctx := context.Background()
	scanner := bufio.NewScanner(os.Stdin)
	linesRemaining := 0
	processesRunning := semaphore.NewWeighted(MaxProcesses)

	for scanner.Scan() {
		if linesRemaining == 0 {
			linesRemaining = MaxLinesPerProcess
			_ = processesRunning.Acquire(ctx, 1)
			linesChannel = make(chan string, MaxLinesPerProcess)
			go subprocess(linesChannel, processesRunning)
		}

		linesChannel <- scanner.Text()
		linesRemaining--

		if linesRemaining == 0 {
			close(linesChannel)
		}
	}

	if linesRemaining > 0 {
		close(linesChannel)
	}
	_ = processesRunning.Acquire(ctx, MaxProcesses)
}
