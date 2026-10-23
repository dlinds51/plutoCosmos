Gem::Specification.new do |spec|
  spec.name          = 'openc3-cosmos-plutosdr'
  spec.version       = '0.7.0'
  spec.authors       = ['Pluto COSMOS Starter']
  spec.summary       = 'Pluto SDR spectrum, ADS-B and stereo FM/RDS for COSMOS'
  spec.description   = 'PlutoSDR spectrum waterfall, ADS-B aircraft telemetry and map, WSLg stereo FM playback, RDS metadata and audio spectrum in native COSMOS screens'
  spec.files         = Dir.glob('plugin.txt') + Dir.glob('targets/**/*').select { |f| File.file?(f) }
  spec.require_paths = ['lib']
end
