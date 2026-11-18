package main

import (
	"context"
	"gopkg.in/yaml.v2"
	"io/ioutil"
	"log"
	"os"
	"os/exec"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
)

var hostname string
var mirroringMutex sync.Mutex

func commandMirroring(client mqtt.Client, mode string) {
	if !mirroringMutex.TryLock() {
		return
	}
	defer mirroringMutex.Unlock()
	client.Publish(getTopicPrefix()+"/status/mirroring_action", 1, true, "Working: "+mode).Wait()
	executable, err := os.Executable()
	if err != nil {
		log.Printf("Mirroring: %v", err)
		return
	}
	helper := strings.TrimSuffix(executable, "/mac2mqtt") + "/office-mirroring"
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Second)
	defer cancel()
	output, err := exec.CommandContext(ctx, helper, mode).CombinedOutput()
	result := strings.TrimSpace(string(output))
	if err != nil {
		result = "Error: " + result
		if result == "Error: " {
			result += err.Error()
		}
	}
	log.Printf("Mirroring: %s", result)
	if len(result) > 250 {
		result = result[:250]
	}
	client.Publish(getTopicPrefix()+"/status/mirroring_action", 1, true, result).Wait()
}

type config struct {
	TLS      bool   `yaml:"mqtt_tls"`
	CAFile   string `yaml:"mqtt_ca_file"`
	Ip       string `yaml:"mqtt_ip"`
	Port     string `yaml:"mqtt_port"`
	User     string `yaml:"mqtt_user"`
	Password string `yaml:"mqtt_password"`
}

func (c *config) getConfig() *config {

	configContent, err := ioutil.ReadFile("mac2mqtt.yaml")
	if err != nil {
		log.Fatal(err)
	}

	err = yaml.Unmarshal(configContent, c)
	if err != nil {
		log.Fatal(err)
	}

	if c.Ip == "" {
		log.Fatal("Must specify mqtt_ip in mac2mqtt.yaml")
	}

	if c.Port == "" {
		log.Fatal("Must specify mqtt_port in mac2mqtt.yaml")
	}

	if c.User == "" {
		log.Fatal("Must specify mqtt_user in mac2mqtt.yaml")
	}

	if c.Password == "" {
		log.Fatal("Must specify mqtt_password in mac2mqtt.yaml")
	}

	return c
}

func getHostname() string {

	hostname, err := os.Hostname()

	if err != nil {
		log.Fatal(err)
	}

	// "name.local" => "name"
	firstPart := strings.Split(hostname, ".")[0]

	// remove all symbols, but [a-zA-Z0-9_-]
	reg, err := regexp.Compile("[^a-zA-Z0-9_-]+")
	if err != nil {
		log.Fatal(err)
	}
	firstPart = reg.ReplaceAllString(firstPart, "")

	return firstPart
}

func runCommand(name string, arg ...string) error {
	return exec.Command(name, arg...).Run()
}

func commandSleep() error        { return runCommand("pmset", "sleepnow") }
func commandDisplaySleep() error { return runCommand("pmset", "displaysleepnow") }
func commandDisplayWake() error  { return runCommand("/usr/bin/caffeinate", "-u", "-t", "5") }
func commandShutdown() error {
	if os.Getuid() == 0 {
		return runCommand("shutdown", "-h", "now")
	}
	return runCommand("/usr/bin/osascript", "-e", `tell app "System Events" to shut down`)
}

var messagePubHandler mqtt.MessageHandler = func(client mqtt.Client, msg mqtt.Message) {
	log.Printf("Received message: %s from topic: %s\n", msg.Payload(), msg.Topic())
}

func getMQTTClient(c config) mqtt.Client {
	opts, err := brokerOptions(c)
	if err != nil {
		log.Fatal(err)
	}
	readiness := &commandReadiness{retry: 15 * time.Second, timeout: 15 * time.Second}
	opts.SetWriteTimeout(10 * time.Second)
	opts.SetCustomOpenConnectionFn(readiness.open)
	opts.OnConnect = readiness.connected
	opts.OnConnectionLost = func(_ mqtt.Client, err error) { log.Printf("Disconnected from MQTT: %v", err) }
	opts.SetWill(getTopicPrefix()+"/status/alive", "false", 1, true)

	client := mqtt.NewClient(opts)
	for {
		token := client.Connect()
		token.Wait()
		if token.Error() == nil {
			break
		}
		log.Printf("MQTT connection failed; retrying in 15 seconds: %v", token.Error())
		time.Sleep(15 * time.Second)
	}

	return client
}

func getTopicPrefix() string {
	return "mac2mqtt/" + hostname
}

var powerActions = map[string]func() error{
	"sleep":        commandSleep,
	"displaysleep": commandDisplaySleep,
	"displaywake":  commandDisplayWake,
	"shutdown":     commandShutdown,
}

func dispatchPowerCommand(msg mqtt.Message, actions map[string]func() error) {
	if msg.Retained() {
		return
	}
	command, ok := strings.CutPrefix(msg.Topic(), getTopicPrefix()+"/command/")
	if !ok {
		return
	}
	action := actions[command]
	if action == nil {
		return
	}
	payload := msg.Payload()
	if len(payload) == len(command) && string(payload) == command {
		if err := action(); err != nil {
			log.Printf("Power command %s failed: %v", command, err)
		}
	}
}

func handleMessage(client mqtt.Client, msg mqtt.Message) {
	if msg.Topic() == getTopicPrefix()+"/command/mirroring" && !msg.Retained() {
		mode := string(msg.Payload())
		if mode == "start" || mode == "stop" || mode == "cameras" {
			go commandMirroring(client, mode)
		}
	}

	systemAudio.handleAudioCommand(client, msg, runAudioScript)

	dispatchPowerCommand(msg, powerActions)

}

var batteryPercent = regexp.MustCompile(`(^|[[:space:]])([0-9]{1,3})%(;|[[:space:]]|$)`)

func readBattery() ([]byte, error) {
	return exec.Command("/usr/bin/pmset", "-g", "batt").Output()
}

func updateBattery(client mqtt.Client, read func() ([]byte, error)) {
	output, err := read()
	if err != nil {
		log.Printf("Could not read battery status: %v", err)
		return
	}
	match := batteryPercent.FindSubmatch(output)
	if match == nil {
		return // Desktop Macs can report AC power without a battery.
	}
	percent, _ := strconv.Atoi(string(match[2]))
	if percent > 100 {
		return
	}
	token := client.Publish(getTopicPrefix()+"/status/battery", 0, false, strconv.Itoa(percent))
	token.Wait()
}

func main() {

	log.Println("Started")

	var c config
	c.getConfig()

	var wg sync.WaitGroup

	hostname = getHostname()
	mqttClient := getMQTTClient(c)

	volumeTicker := time.NewTicker(2 * time.Second)
	batteryTicker := time.NewTicker(60 * time.Second)

	wg.Add(1)
	go func() {
		for {
			select {
			case _ = <-volumeTicker.C:
				systemAudio.updateAudio(mqttClient, runAudioScript)

			case _ = <-batteryTicker.C:
				updateBattery(mqttClient, readBattery)
			}
		}
	}()

	wg.Wait()

}
