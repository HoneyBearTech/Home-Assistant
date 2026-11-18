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

func getCommandOutput(name string, arg ...string) string {
	cmd := exec.Command(name, arg...)

	stdout, err := cmd.Output()
	if err != nil {
		log.Fatal(err)
	}

	stdoutStr := string(stdout)
	stdoutStr = strings.TrimSuffix(stdoutStr, "\n")

	return stdoutStr
}

func getMuteStatus() bool {
	output := getCommandOutput("/usr/bin/osascript", "-e", "output muted of (get volume settings)")

	b, err := strconv.ParseBool(output)
	if err != nil {
		log.Fatal(err)
	}

	return b
}

func getCurrentVolume() int {
	output := getCommandOutput("/usr/bin/osascript", "-e", "output volume of (get volume settings)")

	i, err := strconv.Atoi(output)
	if err != nil {
		log.Fatal(err)
	}

	return i
}

func runCommand(name string, arg ...string) {
	cmd := exec.Command(name, arg...)

	_, err := cmd.Output()
	if err != nil {
		log.Fatal(err)
	}
}

// from 0 to 100
func setVolume(i int) {
	runCommand("/usr/bin/osascript", "-e", "set volume output volume "+strconv.Itoa(i))
}

// true - turn mute on
// false - turn mute off
func setMute(b bool) {
	runCommand("/usr/bin/osascript", "-e", "set volume output muted "+strconv.FormatBool(b))
}

func runPowerCommand(name string, arg ...string) error {
	return exec.Command(name, arg...).Run()
}

func commandSleep() error        { return runPowerCommand("pmset", "sleepnow") }
func commandDisplaySleep() error { return runPowerCommand("pmset", "displaysleepnow") }
func commandDisplayWake() error  { return runPowerCommand("/usr/bin/caffeinate", "-u", "-t", "5") }
func commandShutdown() error {
	if os.Getuid() == 0 {
		return runPowerCommand("shutdown", "-h", "now")
	}
	return runPowerCommand("/usr/bin/osascript", "-e", `tell app "System Events" to shut down`)
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

func handlePowerCommand(msg mqtt.Message, command string, action func() error) {
	// Subscribing again can replay a retained command from an earlier session.
	if msg.Retained() || msg.Topic() != getTopicPrefix()+"/command/"+command || string(msg.Payload()) != command {
		return
	}
	if err := action(); err != nil {
		log.Printf("Power command %s failed: %v", command, err)
	}
}

func handleMessage(client mqtt.Client, msg mqtt.Message) {
	if msg.Topic() == getTopicPrefix()+"/command/mirroring" && !msg.Retained() {
		mode := string(msg.Payload())
		if mode == "start" || mode == "stop" || mode == "cameras" {
			go commandMirroring(client, mode)
		}
	}

	if msg.Topic() == getTopicPrefix()+"/command/volume" {

		i, err := strconv.Atoi(string(msg.Payload()))
		if err == nil && i >= 0 && i <= 100 {

			setVolume(i)

			updateVolume(client)
			updateMute(client)

		} else {
			log.Println("Incorrect value")
		}

	}

	if msg.Topic() == getTopicPrefix()+"/command/mute" {

		b, err := strconv.ParseBool(string(msg.Payload()))
		if err == nil {
			setMute(b)

			updateVolume(client)
			updateMute(client)

		} else {
			log.Println("Incorrect value")
		}

	}

	handlePowerCommand(msg, "sleep", commandSleep)
	handlePowerCommand(msg, "displaysleep", commandDisplaySleep)
	handlePowerCommand(msg, "shutdown", commandShutdown)
	handlePowerCommand(msg, "displaywake", commandDisplayWake)
}

func updateVolume(client mqtt.Client) {
	token := client.Publish(getTopicPrefix()+"/status/volume", 0, false, strconv.Itoa(getCurrentVolume()))
	token.Wait()
}

func updateMute(client mqtt.Client) {
	token := client.Publish(getTopicPrefix()+"/status/mute", 0, false, strconv.FormatBool(getMuteStatus()))
	token.Wait()
}

func getBatteryChargePercent() string {

	output := getCommandOutput("/usr/bin/pmset", "-g", "batt")

	// $ /usr/bin/pmset -g batt
	// Now drawing from 'Battery Power'
	//  -InternalBattery-0 (id=4653155)        100%; discharging; 20:00 remaining present: true

	r := regexp.MustCompile(`(\d+)%`)
	percent := r.FindStringSubmatch(output)[1]

	return percent
}

func updateBattery(client mqtt.Client) {
	token := client.Publish(getTopicPrefix()+"/status/battery", 0, false, getBatteryChargePercent())
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
				updateVolume(mqttClient)
				updateMute(mqttClient)

			case _ = <-batteryTicker.C:
				updateBattery(mqttClient)
			}
		}
	}()

	wg.Wait()

}
